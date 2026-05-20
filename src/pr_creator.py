from __future__ import annotations

from typing import TYPE_CHECKING

from github import Github
from rich.console import Console

if TYPE_CHECKING:
    from src.config import GitConfig

console = Console()

# PR/MR 描述中堆栈区段的字符上限。
# GitHub PR body 上限 65536，GitLab 上限 1,000,000；过滤后堆栈一般 1k-5k，
# 设 60000 给两个平台都留足余量，同时防御性兜底超长输入撑爆页面。
_ERROR_MESSAGE_LIMIT = 60000


def _truncate(text: str, limit: int = _ERROR_MESSAGE_LIMIT) -> str:
    """超过上限时尾部追加省略提示，避免悄无声息地截断。"""
    if len(text) <= limit:
        return text
    head = text[:limit]
    return f"{head}\n... (后续 {len(text) - limit} 字符已省略)"


_BODY_TEMPLATE = """\
## 自动修复报告

### 触发原因
```
{error_message}
```

### 修复说明
本 PR 由 **fix-bug** 自动生成，已通过本地测试。
请 Review 后合并，或关闭此 PR 手动处理。

---
*由 fix-bug 自动创建*
"""


class PRCreator:
    """GitHub Pull Request 创建器。"""

    def __init__(self, token: str, repo_slug: str):
        self.gh = Github(token)
        self.repo = self.gh.get_repo(repo_slug)

    def create(self, branch_name: str, base_branch: str, error_message: str) -> str:
        title = f"[AutoFix] {branch_name}"
        body = _BODY_TEMPLATE.format(error_message=_truncate(error_message))

        console.print(f"[cyan]正在创建 GitHub PR: {title}[/cyan]")
        pr = self.repo.create_pull(
            title=title,
            body=body,
            head=branch_name,
            base=base_branch,
        )
        console.print(f"[green]✓ PR 已创建: {pr.html_url}[/green]")
        return pr.html_url


class GitLabMRCreator:
    """GitLab Merge Request 创建器，支持企业版自定义域名。"""

    def __init__(self, token: str, repo_slug: str, gitlab_url: str = "https://gitlab.com"):
        import gitlab  # 延迟导入，未安装时不影响 GitHub 流程
        self.gl = gitlab.Gitlab(gitlab_url, private_token=token)
        self.project = self.gl.projects.get(repo_slug)

    def create(self, branch_name: str, base_branch: str, error_message: str) -> str:
        title = f"[AutoFix] {branch_name}"
        body = _BODY_TEMPLATE.format(error_message=_truncate(error_message))

        console.print(f"[cyan]正在创建 GitLab PR: {title}[/cyan]")
        mr = self.project.mergerequests.create({
            "source_branch": branch_name,
            "target_branch": base_branch,
            "title": title,
            "description": body,
            "remove_source_branch": True,
        })
        console.print(f"[green]✓ PR 已创建: {mr.web_url}[/green]")
        return mr.web_url


def _extract_gitlab_url(repo_url: str) -> str:
    """从仓库地址自动提取 GitLab 服务器根域名。"""
    if repo_url.startswith("http"):
        from urllib.parse import urlparse
        p = urlparse(repo_url)
        return f"{p.scheme}://{p.netloc}"
    return "https://gitlab.com"


def create_review_request(
    git_cfg: "GitConfig",
    branch_name: str,
    base_branch: str,
    error_message: str,
) -> str:
    """根据 platform 自动选择 PRCreator 或 GitLabMRCreator，返回 PR/MR URL。
    未配置 token 或 repo_slug 时返回空字符串。
    """
    if git_cfg.platform == "gitlab":
        token = git_cfg.gitlab_token
        if not token or not git_cfg.repo_slug:
            console.print("[yellow]GitLab token 或仓库路径未配置，跳过 PR 创建[/yellow]")
            return ""
        gitlab_url = _extract_gitlab_url(git_cfg.repo_url)
        creator: PRCreator | GitLabMRCreator = GitLabMRCreator(token, git_cfg.repo_slug, gitlab_url)
    else:
        token = git_cfg.github_token
        if not token or not git_cfg.repo_slug:
            console.print("[yellow]GitHub token 未配置，跳过 PR 创建[/yellow]")
            return ""
        creator = PRCreator(token, git_cfg.repo_slug)

    return creator.create(branch_name, base_branch, error_message)
