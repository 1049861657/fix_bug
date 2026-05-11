from __future__ import annotations

from github import Github
from rich.console import Console

console = Console()

PR_BODY_TEMPLATE = """\
## 自动修复报告

### 触发原因
```
{error_message}
```

### 修复说明
本 PR 由 **fix-bug** 自动生成，已通过本地测试。
请 Review 后合并，或关闭此 PR 手动处理。

---
*由 [fix-bug](https://github.com) 自动创建*
"""


class PRCreator:
    def __init__(self, token: str, repo_slug: str):
        self.gh = Github(token)
        self.repo = self.gh.get_repo(repo_slug)

    def create(
        self,
        branch_name: str,
        base_branch: str,
        error_message: str,
    ) -> str:
        title = f"[AutoFix] {branch_name}"
        body = PR_BODY_TEMPLATE.format(error_message=error_message[:500])

        console.print(f"[cyan]正在创建 PR: {title}[/cyan]")

        pr = self.repo.create_pull(
            title=title,
            body=body,
            head=branch_name,
            base=base_branch,
        )

        console.print(f"[green]✓ PR 已创建: {pr.html_url}[/green]")
        return pr.html_url
