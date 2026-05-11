from __future__ import annotations

from datetime import datetime
from pathlib import Path

from git import Repo
from rich.console import Console

console = Console()


class GitManager:
    def __init__(self, repo_path: str, remote: str, base_branch: str):
        self.repo = Repo(Path(repo_path).resolve())
        self.remote = remote
        self.base_branch = base_branch
        self.branch_name: str = ""

    def create_fix_branch(self) -> str:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.branch_name = f"fix/auto-{timestamp}"

        origin = self.repo.remotes[self.remote]
        console.print(f"[cyan]正在拉取最新代码 ({self.base_branch})...[/cyan]")
        origin.fetch()

        base_ref = f"{self.remote}/{self.base_branch}"
        new_branch = self.repo.create_head(self.branch_name, base_ref)
        new_branch.checkout()

        console.print(f"[green]✓ 已切换到新分支: {self.branch_name}[/green]")
        return self.branch_name

    def push_branch(self) -> None:
        console.print(f"[cyan]正在推送分支 {self.branch_name}...[/cyan]")
        self.repo.remotes[self.remote].push(
            refspec=f"refs/heads/{self.branch_name}:refs/heads/{self.branch_name}",
        )
        console.print(f"[green]✓ 分支已推送[/green]")

    def has_changes(self) -> bool:
        return self.repo.is_dirty(untracked_files=True)

    def checkout_base(self) -> None:
        self.repo.heads[self.base_branch].checkout()
