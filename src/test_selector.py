"""测试命令窄化工具。

把原始 test_cmd 转换为只跑指定测试类的命令，用于 Step 3 的独立验证。
绕开仓库里预存的脏测试（如依赖 Nacos/Spring 上下文），只验证 AI 新写的复现测试。

设计原则：
- 纯函数 + 单元可测；不依赖文件系统、不调子进程
- 对未识别的命令保持原样返回（保守降级，永不破坏既有流程）
- 同时支持 Maven (-Dtest=) / Gradle (--tests) / pytest (::node)
"""
from __future__ import annotations

import re
import shlex

# 在测试命令中识别测试运行器：键为正则（匹配 token），值为"窄化器"函数名
_MAVEN_TOKENS = ("mvn", "mvnd", "mvnw", "./mvnw", "mvnw.cmd")
_GRADLE_TOKENS = ("gradle", "gradlew", "./gradlew", "gradlew.bat")
_PYTEST_TOKENS = ("pytest", "py.test")

# Surefire / Failsafe 已存在的过滤参数（出现则不再追加新的）
_MAVEN_TEST_FLAG_RE = re.compile(r"^-Dtest=", re.IGNORECASE)


def _split_segments(cmd: str) -> list[str]:
    """按 shell 串联符切分命令，保留分隔符以便重新拼装。

    例：'mvn install -DskipTests && mvn test -q'
     → ['mvn install -DskipTests', '&&', 'mvn test -q']
    """
    parts: list[str] = []
    buf: list[str] = []
    i, n = 0, len(cmd)
    while i < n:
        c = cmd[i]
        nxt = cmd[i + 1] if i + 1 < n else ""
        # 双字符运算符：&& || ;;
        if (c, nxt) in (("&", "&"), ("|", "|")):
            if buf:
                parts.append("".join(buf).strip())
                buf = []
            parts.append(c + nxt)
            i += 2
            continue
        if c in (";", "&"):
            if buf:
                parts.append("".join(buf).strip())
                buf = []
            parts.append(c)
            i += 1
            continue
        buf.append(c)
        i += 1
    if buf:
        tail = "".join(buf).strip()
        if tail:
            parts.append(tail)
    return parts


def _runner_of(tokens: list[str]) -> str:
    """识别命令首个非 cd 段的 runner 类型。"""
    head = ""
    for t in tokens:
        # 跳过 'cd dir' 这类前缀（test_cmd 在 cmd_dir 模式下会拼 'cd ...&& mvn ...'）
        if t == "cd":
            break  # cd 后跟目录，整个段不是测试段；退到外层处理下一段
        head = t
        break
    base = head.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].lower()
    if base in {b.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].lower() for b in _MAVEN_TOKENS}:
        return "maven"
    if base in {b.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].lower() for b in _GRADLE_TOKENS}:
        return "gradle"
    if base in _PYTEST_TOKENS:
        return "pytest"
    return ""


def _narrow_maven(tokens: list[str], class_names: list[str]) -> list[str]:
    """为 Maven 段追加/替换 -Dtest 与 -DfailIfNoTests=false。

    若已显式指定 -Dtest=...，保留用户意图、不覆盖（用户可能正在调试）。
    """
    has_dtest = any(_MAVEN_TEST_FLAG_RE.match(t) for t in tokens)
    has_fail_flag = any(t.startswith("-DfailIfNoTests=") for t in tokens)
    out = list(tokens)
    if not has_dtest:
        out.append(f"-Dtest={','.join(class_names)}")
    if not has_fail_flag:
        out.append("-DfailIfNoTests=false")
    return out


def _narrow_gradle(tokens: list[str], class_names: list[str]) -> list[str]:
    """为 Gradle 段追加 --tests 过滤（每个类一个 --tests）。"""
    out = list(tokens)
    has_filter = any(t == "--tests" for t in tokens)
    if not has_filter:
        for fqcn in class_names:
            out += ["--tests", fqcn]
    return out


def _narrow_segment(segment: str, runner_hint: str, class_names: list[str]) -> str:
    """对单个命令段做窄化（仅当 runner 匹配时）。"""
    try:
        tokens = shlex.split(segment, posix=False)
    except ValueError:
        return segment  # 无法解析则保持原样
    if not tokens:
        return segment

    # 处理 'cd <dir> && mvn test' 这种结构：找出真正的 runner token
    # _split_segments 已经把 && 切开了，但 'cd dir && mvn test' 在 cmd_dir 拼接中
    # 是作为一整段（中间没有 &&）出现的——其实不会，cmd_dir 拼接的串里包含 &&，
    # 这里到达的 segment 一定不含 && / ; 等。
    runner = _runner_of(tokens)
    if runner != runner_hint:
        return segment

    if runner == "maven":
        return " ".join(_narrow_maven(tokens, class_names))
    if runner == "gradle":
        return " ".join(_narrow_gradle(tokens, class_names))
    if runner == "pytest":
        # pytest 走基于 nodeid 的过滤；class_names 此时应为 nodeid（兼容 Python 项目）
        return " ".join(tokens + class_names)
    return segment


def narrow_test_cmd(original_cmd: str, class_names: list[str]) -> str:
    """将原始测试命令窄化为只跑给定测试类的命令。

    Args:
        original_cmd: 来自配置的原始 test_cmd（可能含 `&&` 串联多步）
        class_names: AI 新写的测试类全限定名（Java）或 pytest nodeid（Python）

    Returns:
        窄化后的命令字符串。若 class_names 为空或命令未识别，
        原样返回 original_cmd（让上层逻辑决定是否跳过 Step 3）。
    """
    if not class_names or not original_cmd.strip():
        return original_cmd

    segments = _split_segments(original_cmd)
    if not segments:
        return original_cmd

    # 先识别整条命令的"主 runner"：扫描所有段，找出第一个能识别的 runner
    main_runner = ""
    for seg in segments:
        if seg in ("&&", "||", ";", "&"):
            continue
        try:
            tks = shlex.split(seg, posix=False)
        except ValueError:
            continue
        r = _runner_of(tks)
        if r:
            main_runner = r
            break
    if not main_runner:
        return original_cmd

    # 多段命令的策略：保留 install/build 等前置段，只改最后一个 runner 段
    # 这能正确处理 'mvn install -DskipTests && mvn test -pl X' 这种模式
    target_idx = -1
    for i in range(len(segments) - 1, -1, -1):
        seg = segments[i]
        if seg in ("&&", "||", ";", "&"):
            continue
        try:
            tks = shlex.split(seg, posix=False)
        except ValueError:
            continue
        if _runner_of(tks) == main_runner:
            # Maven 子命令需是 test/verify/integration-test 才窄化；其他（install/compile）跳过
            if main_runner == "maven":
                goals = {t for t in tks if not t.startswith("-") and t not in _MAVEN_TOKENS}
                if not (goals & {"test", "verify", "integration-test", "surefire:test"}):
                    continue
            target_idx = i
            break
    if target_idx < 0:
        return original_cmd

    segments[target_idx] = _narrow_segment(segments[target_idx], main_runner, class_names)
    return " ".join(segments)
