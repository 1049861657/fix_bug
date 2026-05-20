"""Maven 多模块项目的模块自动定位器。

给定一段报错堆栈和仓库根目录，扫描所有 pom.xml 对应的源码树，
找出**包含报错类**的模块名（artifactId 或目录名）。

设计原则：
- 纯函数 + 文件系统只读，零外部依赖（无需 XML 解析）
- 找不到模块时返回 None，调用方应保守降级（不加 -pl，跑全量）
- 仅依赖 `<module>/src/main/java/<package_path>/<Class>.java` 的存在性
- 缓存模块清单避免重复 IO
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

# 主匹配：Java 标准堆栈帧
#   "\tat com.foo.Bar.method(Bar.java:42)"
#   "\tat com.foo.Bar$Inner.method(Bar.java:42)"
# 捕获组1 = 类全限定名（含 $ 内部类）
_STACK_AT_RE = re.compile(r"^\s*at\s+([\w$.]+)\.[\w$<>]+\([\w$.]+:\d+\)")

# 备用匹配：日志框架打印的 logger 引用格式（无 "at" 前缀、无 "(File.java:行号)" 括号）
#   "[ERROR] com.foo.bar.MyService.handle:280 - 业务消息"
#   "[INFO ] com.foo.bar.MyService.handle:280 ..."
# 捕获组1 = 类全限定名，要求 package 至少有一段小写、类名首字母大写
_LOGGER_REF_RE = re.compile(r"\b((?:[a-z][\w]*\.)+[A-Z][\w$]*)\.[\w$<>]+:\d+")

# 备用：从异常头部 / 自定义日志中提取类引用（如 "AssetDetailServiceHelper.java:624"）
_FILE_REF_RE = re.compile(r"\b([A-Z]\w+)\.java[:\s]")

_SRC_MAIN = "src/main/java"
_SRC_TEST = "src/test/java"


@dataclass(frozen=True)
class ModuleInfo:
    """一个 Maven 模块的最小信息：相对仓库根的目录名 + 源码根。

    error_class 字段记录"触发本次定位的报错类全限定名"（可能为空），
    用于上层推导 test_dir 的 package 路径，避免把测试丢进 default package。
    """

    name: str                  # 相对仓库根的目录路径，如 "flp-webportal-app"
    src_main: Path             # <repo>/<name>/src/main/java
    src_test: Path             # <repo>/<name>/src/test/java
    error_class: str = ""      # 报错类 FQCN，如 "com.foo.bar.MyService"

    @property
    def error_package(self) -> str:
        """报错类所在 package，如 'com.foo.bar'；无报错类信息时返回 ''。"""
        if not self.error_class or "." not in self.error_class:
            return ""
        return self.error_class.rsplit(".", 1)[0]

    @property
    def test_dir_with_package(self) -> str:
        """推导出 AI 测试文件的统一目录：<module>/src/test/java/autofix/

        所有 AI 生成的测试类统一集中到 `autofix` 包下，便于审查与隔离。
        测试通过反射访问被测代码，因此不需要与原 package 同名。
        """
        if self.name and self.name != ".":
            return f"{self.name}/src/test/java/autofix/"
        return "src/test/java/autofix/"


def _scan_modules(repo_root: Path) -> list[ModuleInfo]:
    """枚举仓库下所有含 `src/main/java` 的子目录作为候选模块。

    不依赖解析 pom.xml —— 任何有 Maven 源码布局的目录都视为模块。
    既覆盖标准 Maven 多模块，也兼容 Gradle / 手写布局。
    """
    if not repo_root.is_dir():
        return []
    modules: list[ModuleInfo] = []
    # 限定扫描深度，避免遍历整个仓库的 target/、node_modules/ 等
    for src_main in repo_root.glob("*/" + _SRC_MAIN):
        if not src_main.is_dir():
            continue
        rel = src_main.relative_to(repo_root).parts[0]  # 模块目录名
        modules.append(ModuleInfo(
            name=rel,
            src_main=src_main,
            src_test=repo_root / rel / _SRC_TEST,
        ))
    # 兼容单模块仓库：根目录本身可能就是 Maven 模块
    root_src = repo_root / _SRC_MAIN
    if root_src.is_dir() and not modules:
        modules.append(ModuleInfo(
            name=".",
            src_main=root_src,
            src_test=repo_root / _SRC_TEST,
        ))
    return modules


def _candidate_classes(error_message: str, stack_filter: str) -> list[str]:
    """从堆栈中按出现顺序提取候选业务类全限定名（去重保序）。

    匹配策略（按优先级）：
    1. Java 标准堆栈帧 `at <FQCN>.method(File.java:line)`（最强信号）
    2. 日志框架打印的 logger 引用 `<FQCN>.method:line`（无 at、无文件名括号）

    若 stack_filter 非空，仅保留前缀匹配的类。
    """
    seen: set[str] = set()
    result: list[str] = []

    def _accept(fqcn: str) -> None:
        outer = fqcn.split("$", 1)[0]
        if stack_filter and not outer.startswith(stack_filter):
            return
        if outer in seen:
            return
        seen.add(outer)
        result.append(outer)

    for line in error_message.splitlines():
        m = _STACK_AT_RE.match(line)
        if m:
            _accept(m.group(1))
            continue
        # 主正则未命中，再尝试 logger 格式（一行可能多次出现，取全部）
        for m2 in _LOGGER_REF_RE.finditer(line):
            _accept(m2.group(1))
    return result


def _find_module_for_class(modules: list[ModuleInfo], fqcn: str) -> ModuleInfo | None:
    """在所有模块的 src/main/java 下寻找该类对应的源文件。

    匹配成功时返回**带 error_class 的新实例**，便于上层推导 package 路径。
    """
    rel_path = Path(*fqcn.split(".")).with_suffix(".java")
    for mod in modules:
        if (mod.src_main / rel_path).is_file():
            return ModuleInfo(
                name=mod.name,
                src_main=mod.src_main,
                src_test=mod.src_test,
                error_class=fqcn,
            )
    return None


def resolve_module(
    repo_root: str | Path,
    error_message: str,
    stack_filter: str = "",
) -> ModuleInfo | None:
    """从堆栈定位报错所属的 Maven 模块。

    Args:
        repo_root: 仓库本地根目录
        error_message: 完整报错文本（含堆栈）
        stack_filter: 业务包前缀（如 "com.finloop"），用于过滤框架噪音

    Returns:
        匹配到的 ModuleInfo（含 error_class）；匹配失败返回 None。
        单模块仓库且无堆栈匹配时，返回仅含 name 的实例（error_class 为空）。
    """
    root = Path(repo_root).resolve()
    modules = _scan_modules(root)
    if not modules:
        return None

    candidates = _candidate_classes(error_message, stack_filter)

    # 单模块仓库：尝试用堆栈类名补全 error_class，否则返回不带 error_class 的实例
    if len(modules) == 1:
        only = modules[0]
        for fqcn in candidates:
            rel = Path(*fqcn.split(".")).with_suffix(".java")
            if (only.src_main / rel).is_file():
                return ModuleInfo(only.name, only.src_main, only.src_test, fqcn)
        return only

    for fqcn in candidates:
        hit = _find_module_for_class(modules, fqcn)
        if hit:
            return hit
    return None


def inject_module_into_cmd(test_cmd: str, module_name: str) -> str:
    """为命令中的 Maven 段注入模块限定参数。

    规则：
    - install / package / compile 段追加 `-pl <module> -am`，确保依赖模块被构建
    - test / verify / surefire:test 段追加 `-pl <module>` **不带 -am**，
      避免 Surefire 在依赖模块上运行 `-Dtest=FixBug_*` 找不到匹配测试时报错
    - 用户已显式 -pl 时尊重原值，不重复注入

    示例：
        'mvn install -DskipTests -q && mvn test -Dtest=FixBug_*'
        → 'mvn install -DskipTests -q -pl X -am && mvn test -Dtest=FixBug_* -pl X'
    """
    if not module_name or module_name == ".":
        return test_cmd
    if "-pl " in test_cmd or "--projects" in test_cmd:
        return test_cmd

    # 按 && || ; 切分，逐段判断 goal 类型再决定注入策略
    import shlex
    segments = re.split(r"(\s*(?:&&|\|\||;)\s*)", test_cmd)
    install_goals = {"install", "package", "compile", "verify", "deploy"}
    test_goals = {"test", "surefire:test", "integration-test", "failsafe:integration-test"}
    maven_runners = {"mvn", "mvnd", "mvnw", "./mvnw", "mvnw.cmd"}

    out: list[str] = []
    for seg in segments:
        if not seg.strip() or re.fullmatch(r"\s*(?:&&|\|\||;)\s*", seg):
            out.append(seg)
            continue
        try:
            tokens = shlex.split(seg, posix=False)
        except ValueError:
            out.append(seg)
            continue
        if not tokens or tokens[0].lower() not in maven_runners:
            out.append(seg)
            continue

        goals = {t for t in tokens[1:] if not t.startswith("-")}
        if goals & install_goals:
            suffix = f" -pl {module_name} -am"
        elif goals & test_goals:
            # test 段不加 -am，避免依赖模块也跑 surefire
            suffix = f" -pl {module_name}"
        else:
            suffix = f" -pl {module_name}"
        out.append(seg.rstrip() + suffix)
    return "".join(out)
