from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule

from src.aider_runner import AiderRunner
from src.config import load_config
from src.git_manager import GitManager, build_auth_url, ensure_aiderignore, ensure_repo
from src.module_resolver import inject_module_into_cmd, resolve_module
from src.notifier import notify_all
from src.pr_creator import create_review_request
from src.test_runner import TestRunner
from src.test_selector import narrow_test_cmd
from src.utils import filter_stack

console = Console()


@click.group()
def cli() -> None:
    """fix-bug — 自动 Bug 修复工具"""


@cli.command()
@click.argument("test_file", type=click.Path(exists=True))
@click.option("--config", "-c", default="config/python.yaml", show_default=True, help="项目配置文件路径（config/ 目录下）")
def verify(test_file: str, config: str) -> None:
    """将外部测试文件复制到目标仓库 tests/ 并运行，验证 bug 是否已修复。"""
    import shutil

    from git import Repo

    cfg = load_config(config)
    ensure_repo(cfg.git.repo_path, cfg.git.repo_url)

    repo = Repo(cfg.git.repo_path)
    console.print(f"[cyan]正在拉取最新代码 ({cfg.git.base_branch})...[/cyan]")
    origin = repo.remotes[cfg.git.remote]
    origin.fetch()
    repo.heads[cfg.git.base_branch].checkout()
    origin.pull()
    console.print(f"[green]✓ 已更新至最新[/green]")

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
@click.option("--config", "-c", default="config/python.yaml", show_default=True, help="项目配置文件路径（config/ 目录下）")
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
    token = cfg.git.gitlab_token if cfg.git.platform == "gitlab" else cfg.git.github_token
    auth_url = build_auth_url(cfg.git.repo_url, cfg.git.platform, token)
    ensure_repo(cfg.git.repo_path, cfg.git.repo_url, auth_url, cfg.git.git_proxy)
    ensure_aiderignore(cfg.git.repo_path)
    git = GitManager(cfg.git.repo_path, cfg.git.remote, cfg.git.base_branch, cfg.git.git_proxy)
    if dry_run:
        branch_name = "fix/dry-run"
        console.print("[yellow]dry-run 模式，跳过分支创建[/yellow]")
    else:
        branch_name = git.create_fix_branch()

    # ── Step 2: Aider 修复 ────────────────────────────────────────
    console.print(Rule("Step 2 · AI 修复"))

    # 多模块自动定位：从堆栈识别报错所属 Maven 模块，自动补全 -pl/-am 与 test_dir
    resolved_mod = resolve_module(cfg.git.repo_path, error_message, cfg.aider.stack_filter)
    effective_test_cmd = cfg.aider.test_cmd
    effective_test_dir = cfg.aider.test_dir
    if resolved_mod and resolved_mod.name != ".":
        effective_test_cmd = inject_module_into_cmd(effective_test_cmd, resolved_mod.name)
        # 若用户未指定 test_dir、或填的是通用 src/test/java/，则按模块+package 补齐
        if not effective_test_dir or effective_test_dir.strip("/") == "src/test/java":
            effective_test_dir = resolved_mod.test_dir_with_package
        console.print(f"[dim]已定位模块: {resolved_mod.name}  测试目录: {effective_test_dir}[/dim]")
    elif not effective_test_dir:
        effective_test_dir = "src/test/java/"

    aider = AiderRunner(
        repo_path=cfg.git.repo_path,
        model=cfg.aider.model,
        test_cmd=effective_test_cmd,
        test_framework=cfg.aider.test_framework,
        test_dir=effective_test_dir,
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
    # 优先窄化到 AI 本轮新增/修改的测试类，绕开仓库历史脏测试
    new_tests = git.added_test_classes() if not dry_run else []
    if new_tests:
        verify_cmd = narrow_test_cmd(aider.test_cmd, new_tests)
        console.print(f"[dim]检测到新增测试 {len(new_tests)} 个，使用窄化命令验证[/dim]")
    else:
        verify_cmd = aider.test_cmd
        console.print("[dim]未检测到新增测试类，回退到完整 test_cmd[/dim]")
    tester = TestRunner(cfg.git.repo_path, verify_cmd)
    test_passed, _ = tester.run()

    if not test_passed:
        console.print("[red]测试未通过，中止推送和 PR 创建，已保留分支供排查[/red]")
        notify_all(
            branch_name=branch_name,
            pr_url="",
            error_summary=error_message,
            test_passed=False,
            project_name=cfg.git.repo_name,
        )
        console.print(Rule("[bold red]流程终止[/bold red]"))
        raise SystemExit(1)

    pr_url = ""
    if dry_run:
        console.print("[yellow]dry-run 模式，跳过推送和 PR 创建[/yellow]")
    else:
        # ── Step 4: 推送分支 ──────────────────────────────────────
        console.print(Rule("Step 4 · 推送分支"))
        has_new = git.has_commits_ahead()
        if has_new:
            git.push_branch()
        else:
            console.print("[yellow]分支无新提交，跳过推送与 PR 创建[/yellow]")

        # ── Step 5: 创建 PR/MR ────────────────────────────────────
        # 无新提交时跳过 PR 创建，避免生成内容为空的 MR
        if has_new:
            console.print(Rule("Step 5 · 创建 PR"))
            try:
                pr_url = create_review_request(cfg.git, branch_name, cfg.git.base_branch, error_message)
            except Exception as exc:
                console.print(f"[yellow]PR 创建失败（可手动创建）: {exc}[/yellow]")

    # ── Step 6: 生成报告 ──────────────────────────────────────────
    console.print(Rule("Step 6 · 生成报告"))
    notify_all(
        branch_name=branch_name,
        pr_url=pr_url,
        error_summary=error_message,
        test_passed=test_passed,
        project_name=cfg.git.repo_name,
    )

    console.print(Rule("[bold green]流程完成[/bold green]"))


@cli.command()
@click.option("--host", default="0.0.0.0", show_default=True, help="监听地址")
@click.option("--port", default=8000, show_default=True, help="监听端口")
@click.option("--reload", is_flag=True, default=False, help="开发模式自动重载")
def web(host: str, port: int, reload: bool) -> None:
    """启动 Web UI（浏览器可视化界面）。"""
    try:
        import uvicorn
    except ImportError:
        console.print("[red]未找到 uvicorn，请先安装：uv add uvicorn fastapi python-multipart[/red]")
        raise SystemExit(1)
    console.print(f"[green]✓ Web UI 启动中 → http://{host}:{port}[/green]")
    uvicorn.run("web.app:app", host=host, port=port, reload=reload)
