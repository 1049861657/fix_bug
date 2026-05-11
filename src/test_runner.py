from __future__ import annotations

import subprocess
from pathlib import Path

from rich.console import Console

console = Console()


class TestRunner:
    def __init__(self, repo_path: str, test_cmd: str):
        self.repo_path = Path(repo_path).resolve()
        self.test_cmd = test_cmd

    def run(self) -> tuple[bool, str]:
        """运行测试，返回 (是否通过, 输出摘要)"""
        console.print(f"[cyan]运行测试: {self.test_cmd}[/cyan]")

        result = subprocess.run(
            self.test_cmd,
            shell=True,
            cwd=self.repo_path,
            capture_output=True,
            text=True,
        )

        output = result.stdout + result.stderr
        passed = result.returncode == 0

        if passed:
            console.print("[green]✓ 测试通过[/green]")
        else:
            console.print("[red]✗ 测试失败[/red]")
            console.print(output[-2000:])   # 只打印最后 2000 字符

        return passed, output
