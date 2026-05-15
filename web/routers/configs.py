from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api", tags=["configs"])

_PROJECT_ROOT = Path(__file__).parent.parent.parent


@router.get("/configs")
async def list_configs():
    """列出项目根目录下所有 .yaml 配置文件。"""
    yamls = sorted(_PROJECT_ROOT.glob("*.yaml"))
    return [{"name": f.name, "path": f.name} for f in yamls]


@router.get("/reports")
async def list_reports():
    """列出 reports/{project}/ 下所有 Markdown 报告（最新在前）。"""
    report_base = _PROJECT_ROOT / "reports"
    if not report_base.exists():
        return []
    # 扫描所有子目录中的 report-*.md
    files = sorted(report_base.glob("*/report-*.md"), reverse=True)
    result = []
    for f in files:
        project = f.parent.name
        result.append({
            "name": f"{project} / {f.name}",
            "id": f"{project}/{f.stem}",
        })
    return result


@router.get("/reports/{report_id:path}")
async def get_report(report_id: str):
    """返回指定报告的 Markdown 原始内容。report_id 格式为 {project}/{stem}。"""
    report_base = _PROJECT_ROOT / "reports"
    path = report_base / f"{report_id}.md"
    if not path.exists():
        raise HTTPException(status_code=404, detail="报告不存在")
    return {"content": path.read_text(encoding="utf-8")}
