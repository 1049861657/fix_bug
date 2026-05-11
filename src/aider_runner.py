from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

console = Console()

PROMPT_GEN_TEST = """\
以下是来自生产环境的报错信息：

=== 报错信息 ===
{error_message}
=================

请完成以下任务：
1. 分析报错，找到对应的源码文件
2. 在 tests/ 目录下创建或补充一个 pytest 测试文件，写一个能复现此 bug 的**失败测试**
3. 不要修复 bug，只写测试

测试文件命名规范：test_<被测模块名>.py
"""

PROMPT_FIX_BUG = """\
以下是来自生产环境的报错信息：

=== 报错信息 ===
{error_message}
=================

tests/ 目录下已有一个能复现此 bug 的失败测试。
请修复源码中的 Bug，使所有测试通过。
只修改必要的源码文件，不要修改测试文件，保持代码风格一致。
"""


def _check_aider() -> None:
    if shutil.which("aider") is None:
        console.print("[red]✗ 未找到 aider 命令，请先安装：[/red]")
        console.print("    uv tool install aider-chat --python 3.13")
        raise SystemExit(1)


def _run_aider(
    prompt: str,
    repo_path: Path,
    model: str,
    test_cmd: str,
    env: dict,
    metadata_file: str,
) -> bool:
    cmd = [
        "aider",
        "--model", model,
        "--message", prompt,
        "--test-cmd", test_cmd,
        "--auto-test",
        "--yes",
        "--no-pretty",
        "--model-metadata-file", metadata_file,
    ]
    result = subprocess.run(cmd, cwd=repo_path, env=env)
    return result.returncode == 0


class AiderRunner:
    def __init__(
        self,
        repo_path: str,
        model: str,
        test_cmd: str,
        api_base: str = "",
        api_key: str = "",
        context_tokens: int = 200000,
    ):
        self.repo_path = Path(repo_path).resolve()
        self.model = model
        self.test_cmd = test_cmd
        self.api_base = api_base
        self.api_key = api_key
        self.context_tokens = context_tokens

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
        return env

    def run(self, error_message: str) -> bool:
        _check_aider()
        env = self._build_env()
        metadata_file = self._write_model_metadata()   # 在 run() 里生成，传给 _run_aider

        console.print(Panel(
            f"模型: [bold]{self.model}[/bold]\n"
            f"API 地址: [bold]{self.api_base or '(默认)'}[/bold]\n"
            f"测试命令: [bold]{self.test_cmd}[/bold]",
            title="[yellow]Aider 配置[/yellow]",
            expand=False,
        ))

        # ── 阶段一：生成复现 bug 的失败测试 ──────────────────────
        console.print("[cyan]阶段一：生成复现 bug 的测试...[/cyan]")
        prompt_test = PROMPT_GEN_TEST.format(error_message=error_message)
        ok = _run_aider(prompt_test, self.repo_path, self.model, self.test_cmd, env, metadata_file)
        if not ok:
            console.print("[yellow]⚠ 测试生成阶段异常，继续尝试修复...[/yellow]")

        # ── 阶段二：修复 bug 直到测试通过 ────────────────────────
        console.print("[cyan]阶段二：修复 Bug...[/cyan]")
        prompt_fix = PROMPT_FIX_BUG.format(error_message=error_message)
        ok = _run_aider(prompt_fix, self.repo_path, self.model, self.test_cmd, env, metadata_file)

        if ok:
            console.print("[green]✓ Aider 修复完成[/green]")
        else:
            console.print("[red]✗ Aider 修复失败[/red]")
        return ok
