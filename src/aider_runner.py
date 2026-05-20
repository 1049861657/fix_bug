from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable

from rich.console import Console
from rich.panel import Panel

console = Console()

PROMPT_FIX = """\
你是自动 Bug 修复 Agent，单轮非交互模式。本轮必须直接输出 SEARCH/REPLACE 编辑块。
repo-map 已加载，需读源码时**主动**输出 `/add <path>`，禁止说"请提供文件"把责任推给用户。
测试失败会再次调用你，因此第一轮不必完美——但必须真动手。

=== 生产环境报错 ===
{error_message}
====================

# 第一步：判定修复类别（决定后续路径与 commit 标签）
报错本质上属于以下三类之一，必须先明确分类再动手：

## [root-cause] —— 业务逻辑 bug（默认路径）
报错来自业务代码本身的逻辑错误：算错值、走错分支、漏判空、状态机错乱等。
→ 走"根因修复"流程，改业务代码。

## [defensive] —— 错误处理路径自身的二次 bug
报错来自**错误处理代码本身**的缺陷，真实故障在更上游：
- ErrorDecoder / ExceptionHandler / @ControllerAdvice 里 NPE / 越界
- catch 块里 `toString()` / `toJSONString()` 再次抛异常
- 拦截器、过滤器、AOP 切面在处理失败响应时崩溃
- 序列化 / 反序列化器在异常输入下崩溃

判别信号：报错堆栈最深处的业务帧在 `*Decoder` / `*Handler` / `*Interceptor` /
`*Resolver` / `*Advice` 一类"处理器"类型上，且异常来自处理**另一个异常或错误响应**的代码路径。

→ **代码改动质量与 [root-cause] 同等**（防御 + 一致性 + 测试），但必须明示
  "这只修了二次 bug，真实故障在上游，需人工继续排查"。
→ commit 标签用 `[defensive]`，PR/报告读者一眼可知"PR 合并 ≠ 任务恢复"。
→ **代码改动处必须加注释** `// TODO(autofix): 上游待查 - <上游方向>`

## [mitigation] —— 找不到根因，纯止血
高门槛，**慎用**。仅当满足**全部**以下条件才允许：
1. 已 `/add` 并读完报错堆栈中**所有**业务帧文件，且在回复中列出文件路径清单
2. 明确解释：读完之后为什么仍然定位不到根因（不能笼统说"逻辑复杂"）
3. 根因确定在你**无法访问**的位置（如 RPC 远端服务、数据库存储过程、外部配置）

不满足上述条件就选 [mitigation] = 偷懒 = 流程失败。

以下行为是 [mitigation] 的常见伪装，请自查避免：
- 用语义不同的字段替换原字段让结果"看起来对"（如把 字段A 当成 字段B 使用）
- 把异常 catch 后 swallow / 把 ERROR 日志降级 / 放松校验
- 加 null 兜底而不查为什么出现 null
若不得不止血，必须保留原日志级别 + 在代码改动处加 `// TODO(autofix): 根因待查 - <具体问题>`

注意：[defensive] ≠ [mitigation]。前者是"该改的必要改动 + 上游待查"，后者是"找不到根因的兜底"。
错误处理路径的 NPE 防御属于 [defensive]，**不要降级为 [mitigation]**。

# 读源码的最低要求（[root-cause] / [defensive] 都适用）
- 必读：报错堆栈中**全部**业务帧涉及的文件（不是只读最顶层那个）
- 数据异常类（金额对不上、数量不一致、null 出现）必读：数据**产生方**而非消费方
  · 例：某汇总值 X 在 `Foo.compute()` 抛错 → 必读 `Foo.compute()` 全部赋值/累加路径，
    以及调用 `Foo.compute()` 的上游传入参数
- 跨方法的链路（A→B→C 都在业务包内）必须沿链读完

# 同仓库参照（强烈推荐，质量倍增器）
准备编辑某个类前，如果该类是"处理器/装饰器/解析器"模式（类名以
`Decoder` / `Handler` / `Interceptor` / `Filter` / `Resolver` / `Advice` / `Converter` 结尾），
**主动 `/add` 同包/同模块下命名相近的姐妹类**，对比它们有没有做你即将做的防御。

· 例：要给 `XxxDecoder` 加空值判断 → 先看同包姐妹 `YyyDecoder` 是否已判空
· 例：要在 `XxxHandler` 加日志降级 → 先看姐妹 `YyyHandler` 用的什么级别

如果姐妹类已有相关防御/处理，你的修复**模式应该向它对齐**（保持一致比"更聪明"重要）。
在诊断段明示："参照 `<姐妹类>:<行号>` 的同型处理，本次按相同模式补齐 `<目标类>`"。

# 修复输出（必须包含 4 项）
1. **类别判定**：明确写出 `修复类别：[root-cause]` / `[defensive]` / `[mitigation]` 之一 + 一句话理由
2. **诊断段**：根因或二次 bug 判断 + 已读文件清单 + 姐妹类参照（如适用）
   · [defensive] 必加 "**真实故障待查**" 子标题，列出上游应排查的具体方向
     （如：远端服务异常响应、依赖网关超时、数据源异常、配置缺失等），给人工排查指路
3. **代码修复**：SEARCH/REPLACE 编辑块。无"最小改动"豁免——根因在 10 行外就改那 10 行
4. **复现测试**：SEARCH/REPLACE 编辑块创建新测试类
   · [defensive] 测试必须模拟"上游失败 + 错误处理路径"组合
     （如 mock 一个错误状态码且响应体为 null 的下游响应）

# 测试硬性要求
- 路径：{test_dir}，`package` 声明必须与该目录一致
- 类名以 `FixBug_` 开头，例 `FixBug_NullXxxField_Test`
- 纯单元测试。禁 @SpringBootTest / @WebMvcTest / @DataJpaTest 等加载 Spring 的注解
- 不依赖配置中心 / DB / 网络 / 文件系统；依赖用 Mockito mock
- 私有 / package-private / 字段一律用反射（setAccessible(true)）。测试与被测不在同一 package
- 构造器依赖传 null 或 mock；一个 bug 一个测试类
- 测试在修复前失败、修复后通过

# 通用禁令
- 不改测试命令、{test_framework} 配置或 CI 文件
- 不删除 / @Disabled 已有测试
- 不为绕过 surefire / CI 错误新建 Placeholder / Stub 测试

# Commit message 格式（强制）
- [root-cause]  → `[auto] [root-cause] fix: <描述>`
- [defensive]   → `[auto] [defensive] fix: <描述>（真实故障待查：<上游方向>）`
- [mitigation]  → `[auto] [mitigation] fix: <描述>`（必须配 TODO 注释）
"""


def _check_aider() -> None:
    if shutil.which("aider") is None:
        console.print("[red]✗ 未找到 aider 命令，请先安装：[/red]")
        console.print("    uv tool install aider-chat --python 3.13")
        raise SystemExit(1)


def _build_cmd(model: str, prompt: str, metadata_file: str, test_cmd: str, auto_test: bool) -> list[str]:
    # 统一使用 OpenAI 兼容协议，自动补全 provider 前缀
    aider_model = model if "/" in model else f"openai/{model}"
    cmd = [
        "aider",
        "--model", aider_model,
        "--message", prompt,
        "--yes-always",
        "--no-pretty",
        "--no-fancy-input",
        "--edit-format", "diff",
        "--model-metadata-file", metadata_file,
        "--map-tokens", "8192",
    ]
    if test_cmd and auto_test:
        cmd += ["--test-cmd", test_cmd, "--auto-test"]
    return cmd


def _run_aider(
    prompt: str,
    repo_path: Path,
    model: str,
    env: dict,
    metadata_file: str,
    test_cmd: str = "",
    auto_test: bool = False,
) -> bool:
    """CLI 模式：直接透传子进程输出到终端（保留颜色和交互效果）。"""
    cmd = _build_cmd(model, prompt, metadata_file, test_cmd, auto_test)
    result = subprocess.run(cmd, cwd=repo_path, env=env)
    return result.returncode == 0


_HEARTBEAT_INTERVAL = 15   # 静默超过此秒数发第一条心跳
_HEARTBEAT_REPEAT   = 30   # 之后每隔此秒数重复一次


def _run_aider_streaming(
    prompt: str,
    repo_path: Path,
    model: str,
    env: dict,
    metadata_file: str,
    log_fn: Callable[[str], None],
    test_cmd: str = "",
    auto_test: bool = False,
    proc_cb: Callable | None = None,
) -> bool:
    """Web 模式：用 Popen 逐行捕获输出，通过 log_fn 回调传递给调用方。"""
    cmd = _build_cmd(model, prompt, metadata_file, test_cmd, auto_test)
    proc = subprocess.Popen(
        cmd,
        cwd=repo_path,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        encoding="utf-8",
        errors="replace",
    )
    if proc_cb:
        proc_cb(proc)

    last_output = [time.monotonic()]   # 最后一次有输出的时间（可变容器供闭包写入）

    def _heartbeat() -> None:
        """静默检测：无输出超过阈值时周期性发送等待提示。"""
        last_sent = 0.0   # 上次发心跳时已静默的秒数
        while proc.poll() is None:
            time.sleep(5)
            silent = time.monotonic() - last_output[0]
            # 首次达到阈值，或距上次发心跳已过 _HEARTBEAT_REPEAT 秒
            if silent >= _HEARTBEAT_INTERVAL and (silent - last_sent) >= _HEARTBEAT_REPEAT:
                last_sent = silent
                mins, secs = divmod(int(silent), 60)
                dur = f"{mins}m {secs:02d}s" if mins else f"{secs}s"
                log_fn(f"⏳ 等待 Aider/LLM 响应中... 已静默 {dur}")

    threading.Thread(target=_heartbeat, daemon=True).start()

    for line in iter(proc.stdout.readline, ""):
        last_output[0] = time.monotonic()
        log_fn(line.rstrip())
    proc.stdout.close()
    proc.wait()
    return proc.returncode == 0


class AiderRunner:
    def __init__(
        self,
        repo_path: str,
        model: str,
        test_cmd: str,
        test_framework: str = "pytest",
        test_dir: str = "tests/",
        cmd_dir: str = "",
        api_base: str = "",
        api_key: str = "",
        context_tokens: int = 200000,
    ):
        self.repo_path = Path(repo_path).resolve()
        self.model = model
        self._proc: subprocess.Popen | None = None
        self.test_framework = test_framework
        self.test_dir = test_dir
        self.api_base = api_base
        self.api_key = api_key
        self.context_tokens = context_tokens
        if cmd_dir:
            self.test_cmd = f"cd {cmd_dir} && {test_cmd}"
        else:
            self.test_cmd = test_cmd

    def cancel(self) -> None:
        """强制终止当前 Aider 子进程。"""
        if self._proc and self._proc.poll() is None:
            self._proc.kill()

    def _write_model_metadata(self) -> str:
        aider_model = self.model if "/" in self.model else f"openai/{self.model}"
        meta = {
            aider_model: {
                "max_tokens": self.context_tokens,
                "max_input_tokens": self.context_tokens,
                "max_output_tokens": 8096,
                "input_cost_per_token": 0,
                "output_cost_per_token": 0,
            }
        }
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        json.dump(meta, f)
        f.close()
        return f.name

    def _build_env(self) -> dict:
        env = {k: v for k, v in os.environ.items() if not k.startswith("AIDER_")}
        if self.api_base:
            env["OPENAI_API_BASE"] = self.api_base
        if self.api_key:
            env["OPENAI_API_KEY"] = self.api_key
        # 强制 aider 子进程使用 UTF-8，避免 Windows 中文环境下 GBK/CP936 乱码
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        return env

    def run(self, error_message: str, log_fn: Callable[[str], None] | None = None) -> bool:
        """执行 Aider 修复。

        log_fn 为 None 时使用 CLI 模式（输出直通终端）；
        提供 log_fn 时使用 Web 流式模式（逐行回调）。
        """
        _check_aider()
        env = self._build_env()
        metadata_file = self._write_model_metadata()

        prompt = PROMPT_FIX.format(
            error_message=error_message,
            test_framework=self.test_framework,
            test_dir=self.test_dir,
        )

        if log_fn is None:
            console.print(Panel(
                f"模型: [bold]{self.model}[/bold]\n"
                f"API 地址: [bold]{self.api_base or '(默认)'}[/bold]\n"
                f"测试命令: [bold]{self.test_cmd}[/bold]",
                title="[yellow]Aider 配置[/yellow]",
                expand=False,
            ))
            console.print("[cyan]正在启动 Aider（分析报错 → 补充测试 → 修复代码）...[/cyan]")
            ok = _run_aider(
                prompt, self.repo_path, self.model, env, metadata_file,
                test_cmd=self.test_cmd, auto_test=True,
            )
        else:
            log_fn(f"模型: {self.model} | 测试命令: {self.test_cmd}")
            log_fn("正在启动 Aider（分析报错 → 补充测试 → 修复代码）...")
            ok = _run_aider_streaming(
                prompt, self.repo_path, self.model, env, metadata_file,
                log_fn=log_fn,
                test_cmd=self.test_cmd,
                auto_test=True,
                proc_cb=lambda p: setattr(self, '_proc', p),
            )

        if log_fn is None:
            if ok:
                console.print("[green]✓ Aider 修复完成[/green]")
            else:
                console.print("[red]✗ Aider 未能完成修复，流程终止[/red]")
        else:
            log_fn("✓ Aider 修复完成" if ok else "✗ Aider 未能完成修复")

        return ok
