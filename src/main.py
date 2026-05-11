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


@click.group()
def cli() -> None:
    """fix-bug — 自动 Bug 修复工具"""


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
    tester = TestRunner(cfg.git.repo_path, cfg.aider.test_cmd)
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
        if cfg.github.token and cfg.github.repo_slug:
            try:
                pr_creator = PRCreator(cfg.github.token, cfg.github.repo_slug)
                pr_url = pr_creator.create(branch_name, cfg.git.base_branch, error_message)
            except Exception as exc:
                console.print(f"[yellow]PR 创建失败（可手动创建）: {exc}[/yellow]")
        else:
            console.print("[yellow]GitHub token 或 repo_slug 未配置，跳过 PR 创建[/yellow]")

    # ── Step 6: 生成报告 ──────────────────────────────────────────
    console.print(Rule("Step 6 · 生成报告"))
    notify_all(
        branch_name=branch_name,
        pr_url=pr_url,
        error_summary=error_message[:300],
        test_passed=test_passed,
    )

    console.print(Rule("[bold green]流程完成[/bold green]"))
