from __future__ import annotations

from datetime import datetime
from pathlib import Path

from rich.console import Console

console = Console()

REPORT_DIR = Path("reports")

REPORT_TEMPLATE = """\
# fix-bug 自动修复报告

**生成时间**: {timestamp}

## 分支

`{branch_name}`

## PR 地址

{pr_url}

## 测试结果

{test_result}

## 错误摘要

```
{error_summary}
```
"""


def notify_all(
    branch_name: str,
    pr_url: str,
    error_summary: str,
    test_passed: bool,
) -> None:
    REPORT_DIR.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report_path = REPORT_DIR / f"report-{timestamp}.md"

    content = REPORT_TEMPLATE.format(
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        branch_name=branch_name,
        pr_url=pr_url if pr_url else "（未创建）",
        test_result="✅ 通过" if test_passed else "❌ 失败",
        error_summary=error_summary,
    )

    report_path.write_text(content, encoding="utf-8")
    console.print(f"[green]✓ 报告已生成: {report_path.resolve()}[/green]")
