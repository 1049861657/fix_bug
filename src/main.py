from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule

from src.aider_runner import AiderRunner
from src.config import load_config
from src.git_manager import GitManager, ensure_repo
from src.notifier import notify_all
from src.pr_creator import PRCreator
from src.test_runner import TestRunner

console = Console()


def filter_stack(error_message: str, app_prefix: str) -> str:
    """过滤堆栈中的框架噪音行，只保留业务代码帧和异常头。

    支持 Java（`\tat ...`）和 Python（`  File "..."` in site-packages）。
    app_prefix 为空时直接返回原文。
    """
    if not app_prefix:
        return error_message

    kept, total_at, removed_at = [], 0, 0
    for line in error_message.splitlines():
        stripped = line.lstrip()
        # Java: at com.xxx / at java.base（框架行以 \tat 开头）
        if stripped.startswith("at "):
            total_at += 1
            if app_prefix in line:
                kept.append(line)
            else:
                removed_at += 1
                continue
        # Python: File ".../site-packages/..." 框架行
        elif stripped.startswith('File "') and "site-packages" in line and app_prefix not in line:
            removed_at += 1
            continue
        else:
            kept.append(line)

    if removed_at:
        kept.append(f"    ... ({removed_at}/{total_at} 框架堆栈帧已省略)")
    return "\n".join(kept)


@click.group()
def cli() -> None:
    """fix-bug — 自动 Bug 修复工具"""


@cli.command()
@click.argument("test_file", type=click.Path(exists=True))
@click.option("--config", "-c", default="config.yaml", show_default=True, help="配置文件路径")
def verify(test_file: str, config: str) -> None:
    """将外部测试文件复制到目标仓库 tests/ 并运行，验证 bug 是否已修复。"""
    import shutil

    cfg = load_config(config)
    ensure_repo(cfg.git.repo_path, cfg.git.repo_url)

    repo_tests_dir = Path(cfg.git.repo_path) / "tests"
    repo_tests_dir.mkdir(exist_ok=True)

    dest = repo_tests_dir / Path(test_file).name
    shutil.copy2(test_file, dest)
    console.print(f"[cyan]已复制测试文件: {dest}[/cyan]")

    tester = TestRunner(cfg.git.repo_path, f"pytest tests/{Path(test_file).name} -v")
    passed, _ = tester.run()

    if passed:
        console.print("[green]✓ 所有测试通过，Bug 已修复[/green]")
    else:
        console.print("[red]✗ 测试未通过，Bug 仍存在[/red]")
        raise SystemExit(1)


@cli.command()
@click.option("--message", "-m", help="直接传入报错信息（字符串）")
@click.option("--log-file", "-f", type=click.Path(exists=True), help="报错日志文件路径")
@click.option("--config", "-c", default="config.yaml", show_default=True, help="配置文件路径")
@click.option("--dry-run", is_flag=True, default=False, help="只运行 Aider，不推送分支和创建 PR")
def run(message: str | None, log_file: str | None, config: str, dry_run: bool) -> None:
    """接收报错信息，自动修复 Bug 并提交 PR。"""

    # ── 读取报错信息 ──────────────────────────────────────────────
    if log_file:
        error_message = Path(log_file).read_text(encoding="utf-8")
    elif message:
        error_message = message
    else:
        console.print("[yellow]请通过 stdin 输入报错信息（Ctrl+D 结束）：[/yellow]")
        error_message = sys.stdin.read()

    if not error_message.strip():
        console.print("[red]错误：报错信息为空[/red]")
        raise SystemExit(1)

    cfg = load_config(config)
    error_message = filter_stack(error_message, cfg.aider.stack_filter)

    console.print(Rule("[bold blue]fix-bug 自动修复流程启动[/bold blue]"))
    console.print(Panel(
        error_message[:400] + ("..." if len(error_message) > 400 else ""),
        title="[red]报错信息[/red]",
        expand=False,
    ))

    # ── Step 1: 创建修复分支 ──────────────────────────────────────
    console.print(Rule("Step 1 · 创建分支"))
    ensure_repo(cfg.git.repo_path, cfg.git.repo_url)
    git = GitManager(cfg.git.repo_path, cfg.git.remote, cfg.git.base_branch)
    if dry_run:
        branch_name = "fix/dry-run"
        console.print("[yellow]dry-run 模式，跳过分支创建[/yellow]")
    else:
        branch_name = git.create_fix_branch()

    # ── Step 2: Aider 修复 ────────────────────────────────────────
    console.print(Rule("Step 2 · AI 修复"))
    aider = AiderRunner(
        repo_path=cfg.git.repo_path,
        model=cfg.aider.model,
        test_cmd=cfg.aider.test_cmd,
        test_framework=cfg.aider.test_framework,
        test_dir=cfg.aider.test_dir,
        cmd_dir=cfg.aider.cmd_dir,
        api_base=cfg.aider.api_base,
        api_key=cfg.aider.api_key,
        context_tokens=cfg.aider.context_tokens,
    )
    fix_ok = aider.run(error_message)

    if not fix_ok:
        console.print("[red]Aider 未能完成修复，流程终止[/red]")
        if not dry_run:
            git.checkout_base()
        raise SystemExit(1)

    # ── Step 3: 再次验证测试 ──────────────────────────────────────
    console.print(Rule("Step 3 · 验证测试"))
    tester = TestRunner(cfg.git.repo_path, aider.test_cmd)
    test_passed, _ = tester.run()

    if not test_passed:
        console.print("[red]测试未通过，中止推送和 PR 创建，已保留分支供排查[/red]")
        notify_all(
            branch_name=branch_name,
            pr_url="",
            error_summary=error_message[:300],
            test_passed=False,
        )
        console.print(Rule("[bold red]流程终止[/bold red]"))
        raise SystemExit(1)

    pr_url = ""
    if dry_run:
        console.print("[yellow]dry-run 模式，跳过推送和 PR 创建[/yellow]")
    else:
        # ── Step 4: 推送分支 ──────────────────────────────────────
        console.print(Rule("Step 4 · 推送分支"))
        if git.has_commits_ahead():
            git.push_branch()
        else:
            console.print("[yellow]分支无新提交，跳过推送[/yellow]")

        # ── Step 5: 创建 PR ───────────────────────────────────────
        console.print(Rule("Step 5 · 创建 PR"))
        if cfg.git.github_token and cfg.git.repo_slug:
            try:
                pr_creator = PRCreator(cfg.git.github_token, cfg.git.repo_slug)
                pr_url = pr_creator.create(branch_name, cfg.git.base_branch, error_message)
            except Exception as exc:
                console.print(f"[yellow]PR 创建失败（可手动创建）: {exc}[/yellow]")
        else:
            console.print("[yellow]GitHub token 未配置，跳过 PR 创建[/yellow]")

    # ── Step 6: 生成报告 ──────────────────────────────────────────
    console.print(Rule("Step 6 · 生成报告"))
    notify_all(
        branch_name=branch_name,
        pr_url=pr_url,
        error_summary=error_message[:300],
        test_passed=test_passed,
    )

    console.print(Rule("[bold green]流程完成[/bold green]"))
