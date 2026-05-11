from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

console = Console()

AIDER_PROMPT_TEMPLATE = """\
以下是来自生产环境的报错信息，请分析根本原因并修复代码中的 Bug。
修复时只修改必要的文件，保持代码风格一致。

=== 报错信息 ===
{error_message}
=================

请直接修复，无需解释。
"""


def _check_aider() -> None:
    if shutil.which("aider") is None:
        console.print("[red]✗ 未找到 aider 命令，请先安装：[/red]")
        console.print("    uv tool install aider-chat")
        raise SystemExit(1)


class AiderRunner:
    def __init__(self, repo_path: str, model: str, test_cmd: str, api_base: str = "", api_key: str = ""):
        self.repo_path = Path(repo_path).resolve()
        self.model = model
        self.test_cmd = test_cmd
        self.api_base = api_base
        self.api_key = api_key

    def run(self, error_message: str) -> bool:
        _check_aider()
        prompt = AIDER_PROMPT_TEMPLATE.format(error_message=error_message)

        console.print(Panel(
            f"模型: [bold]{self.model}[/bold]\n"
            f"API 地址: [bold]{self.api_base or '(默认)'}[/bold]\n"
            f"测试命令: [bold]{self.test_cmd}[/bold]",
            title="[yellow]Aider 配置[/yellow]",
            expand=False,
        ))

        cmd = [
            "aider",
            "--model", self.model,
            "--message", prompt,
            "--test-cmd", self.test_cmd,
            "--auto-test",
            "--yes",
            "--no-pretty",
        ]

        if self.api_base:
            cmd += ["--openai-api-base", self.api_base]
        if self.api_key:
            cmd += ["--openai-api-key", self.api_key]

        console.print("[cyan]正在启动 Aider...[/cyan]")

        result = subprocess.run(cmd, cwd=self.repo_path)

        if result.returncode == 0:
            console.print("[green]✓ Aider 修复完成[/green]")
            return True

        console.print(f"[red]✗ Aider 退出码: {result.returncode}[/red]")
        return False
