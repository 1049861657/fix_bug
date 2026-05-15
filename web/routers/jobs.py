from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _job_dict(j) -> dict:
    d = {
        "id": j.id,
        "config_path": j.config_path,
        "status": j.status,
        "branch": j.branch,
        "pr_url": j.pr_url,
        "error_msg": j.error_msg,
        "created_at": j.created_at,
        "finished_at": j.finished_at,
        "duration_s": None,
    }
    if j.finished_at:
        try:
            s = datetime.fromisoformat(j.created_at)
            e = datetime.fromisoformat(j.finished_at)
            d["duration_s"] = int((e - s).total_seconds())
        except ValueError:
            pass
    return d


def _runner(request: Request):
    return request.app.state.runner


@router.post("", status_code=201)
async def create_job(
    request: Request,
    config_path: str = Form(..., description="配置文件路径，如 config.yaml"),
    error_text: str = Form("", description="报错信息文本"),
    log_file: UploadFile | None = File(None, description="报错日志文件（与 error_text 二选一）"),
):
    """提交一个新的 Bug 修复任务。"""
    if log_file and log_file.filename:
        raw = await log_file.read()
        error_message = raw.decode("utf-8", errors="replace")
    elif error_text.strip():
        error_message = error_text
    else:
        raise HTTPException(status_code=400, detail="error_text 或 log_file 必须提供其一")

    runner = _runner(request)
    try:
        job_id = runner.submit(config_path, error_message)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    return {"id": job_id, "status": "running"}


@router.get("")
async def list_jobs(request: Request):
    """返回所有历史任务（最新在前）。"""
    jobs = _runner(request).store.list_all()
    return [_job_dict(j) for j in jobs]


@router.get("/{job_id}")
async def get_job(job_id: str, request: Request):
    """返回单个任务的状态和元数据。"""
    job = _runner(request).store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return _job_dict(job)


@router.delete("/{job_id}")
async def delete_job(job_id: str, request: Request):
    """删除任务记录及其日志文件。运行中任务不可删除。"""
    try:
        _runner(request).delete_job(job_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"ok": True}


@router.post("/{job_id}/cancel")
async def cancel_job(job_id: str, request: Request):
    """强制终止运行中的任务。"""
    runner = _runner(request)
    job = runner.store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job.status != "running":
        raise HTTPException(status_code=409, detail="任务未在运行中")
    runner.cancel(job_id)
    return {"ok": True}


@router.get("/{job_id}/logs")
async def get_job_logs(job_id: str, request: Request, offset: int = 0):
    """一次性返回任务的全部（或从 offset 起的）日志行（JSON 数组）。"""
    runner = _runner(request)
    job = runner.store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    lines = runner.get_lines(job_id, offset)
    return {"lines": lines, "done": runner.is_done(job_id)}
