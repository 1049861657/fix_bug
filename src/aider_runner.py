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


def _run_aider(
    prompt: str,
    repo_path: Path,
    model: str,
    env: dict,
    metadata_file: str,
    test_cmd: str = "",
    auto_test: bool = False,
) -> bool:
    cmd = [
        "aider",
        "--model", model,
        "--message", prompt,
        "--yes",
        "--no-pretty",
        "--edit-format", "diff",
        "--model-metadata-file", metadata_file,
    ]
    if test_cmd and auto_test:
        cmd += ["--test-cmd", test_cmd, "--auto-test"]
    result = subprocess.run(cmd, cwd=repo_path, env=env)
    return result.returncode == 0


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
        return env

    def run(self, error_message: str) -> bool:
        _check_aider()
        env = self._build_env()
        metadata_file = self._write_model_metadata()

        console.print(Panel(
            f"模型: [bold]{self.model}[/bold]\n"
            f"API 地址: [bold]{self.api_base or '(默认)'}[/bold]\n"
            f"测试命令: [bold]{self.test_cmd}[/bold]",
            title="[yellow]Aider 配置[/yellow]",
            expand=False,
        ))

        console.print("[cyan]正在启动 Aider（分析报错 → 补充测试 → 修复代码）...[/cyan]")
        prompt = PROMPT_FIX.format(
            error_message=error_message,
            test_framework=self.test_framework,
            test_dir=self.test_dir,
        )
        ok = _run_aider(
            prompt, self.repo_path, self.model, env, metadata_file,
            test_cmd=self.test_cmd, auto_test=True,
        )

        if ok:
            console.print("[green]✓ Aider 修复完成[/green]")
        else:
            console.print("[red]✗ Aider 未能完成修复，流程终止[/red]")
        return ok
