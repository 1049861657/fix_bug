from __future__ import annotations

from datetime import datetime
from pathlib import Path

from git import Repo
from rich.console import Console

console = Console()


def ensure_repo(repo_path: str, repo_url: str) -> None:
    """若本地路径不存在则从 repo_url clone；已存在则跳过。"""
    path = Path(repo_path).resolve()
    if path.exists() and (path / ".git").exists():
        return
    if not repo_url:
        raise ValueError(
            f"本地路径 {path} 不存在，且未配置 git.repo_url，无法自动 clone。"
        )
    console.print(f"[cyan]目录不存在，正在 clone: {repo_url} → {path}[/cyan]")
    path.mkdir(parents=True, exist_ok=True)
    Repo.clone_from(repo_url, path)
    console.print(f"[green]✓ Clone 完成[/green]")


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

        # 优先用远程分支作为起点，远程不存在时回退到本地分支
        remote_ref = f"{self.remote}/{self.base_branch}"
        try:
            base_ref = self.repo.commit(remote_ref)
            console.print(f"[dim]基准: {remote_ref}[/dim]")
        except Exception:
            console.print(f"[yellow]远程 {remote_ref} 不存在，回退到本地 {self.base_branch}[/yellow]")
            base_ref = self.repo.heads[self.base_branch].commit

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

    def has_commits_ahead(self) -> bool:
        """当前分支是否有领先于远程基准分支的提交（aider auto-commit 后工作区是干净的）"""
        try:
            base = self.repo.commit(f"{self.remote}/{self.base_branch}")
            ahead = list(self.repo.iter_commits(f"{self.remote}/{self.base_branch}..HEAD"))
            return len(ahead) > 0
        except Exception:
            return self.repo.is_dirty(untracked_files=True)

    def checkout_base(self) -> None:
        self.repo.heads[self.base_branch].checkout()
