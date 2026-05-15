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
你是一个自动 Bug 修复助手。以下是来自生产环境的运行时报错：

=== 报错信息 ===
{error_message}
=================

请按顺序完成以下步骤：

1. **定位根因**：根据报错堆栈，找到出错的源码文件和具体行，解释错误原因
2. **补充测试**：在 {test_dir} 目录创建或修改 {test_framework} 测试以稳定复现此 bug；\
测试必须在修复前失败、修复后通过
3. **修复源码**：以最小改动修复 bug，不引入新的测试失败

限制：
- 不得修改测试命令、{test_framework} 配置或 CI 相关文件
- 不得为了让测试通过而删除或跳过已有测试
- 保持原有代码风格
"""


def _check_aider() -> None:
    if shutil.which("aider") is None:
        console.print("[red]✗ 未找到 aider 命令，请先安装：[/red]")
        console.print("    uv tool install aider-chat --python 3.13")
        raise SystemExit(1)


def _build_cmd(model: str, prompt: str, metadata_file: str, test_cmd: str, auto_test: bool) -> list[str]:
    cmd = [
        "aider",
        "--model", model,
        "--message", prompt,
        "--yes-always",
        "--no-pretty",
        "--edit-format", "diff",
        "--model-metadata-file", metadata_file,
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


_HEARTBEAT_INTERVAL = 15   # 静默超过此秒数开始发心跳
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

    last_output = [time.monotonic()]   # 最后一次有输出的时间（可变容器供闭包写入）

    def _heartbeat() -> None:
        """静默检测：无输出超过阈值时周期性发送等待提示。"""
        while proc.poll() is None:
            time.sleep(5)
            silent = time.monotonic() - last_output[0]
            if silent >= _HEARTBEAT_INTERVAL and int(silent) % _HEARTBEAT_REPEAT < 5:
                mins, secs = divmod(int(silent), 60)
                dur = f"{mins}m {secs:02d}s" if mins else f"{secs}s"
                log_fn(f"⏳ 等待 Aider/LLM 响应中... (已静默 {dur}，进程仍在运行)")

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
        self.test_framework = test_framework
        self.test_dir = test_dir
        self.api_base = api_base
        self.api_key = api_key
        self.context_tokens = context_tokens
        if cmd_dir:
            self.test_cmd = f"cd {cmd_dir} && {test_cmd}"
        else:
            self.test_cmd = test_cmd

    def _write_model_metadata(self) -> str:
        meta = {
            self.model: {
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
            )

        if log_fn is None:
            if ok:
                console.print("[green]✓ Aider 修复完成[/green]")
            else:
                console.print("[red]✗ Aider 未能完成修复，流程终止[/red]")
        else:
            log_fn("✓ Aider 修复完成" if ok else "✗ Aider 未能完成修复")

        return ok
