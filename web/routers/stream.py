from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/api/jobs", tags=["stream"])

_POLL_INTERVAL = 0.15  # seconds


@router.get("/{job_id}/stream")
async def stream_logs(job_id: str, request: Request, offset: int = 0):
    """SSE 实时日志流。

    - 运行中的任务：持续推送新行，直到任务结束后发送 `event: done`。
    - 已完成的任务：立即回放全部日志，然后发送 `event: done`。
    - 客户端断开时自动停止推送。
    """
    runner = request.app.state.runner
    job = runner.store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")

    async def generate():
        current = offset
        while True:
            if await request.is_disconnected():
                break

            lines = runner.get_lines(job_id, current)
            for line in lines:
                safe = line.replace("\r\n", " ").replace("\n", " ").replace("\r", "")
                yield f"data: {safe}\n\n"
                current += 1

            done = runner.is_done(job_id)
            remaining = runner.get_lines(job_id, current)

            if done and not remaining:
                yield "event: done\ndata: end\n\n"
                break

            if not done:
                await asyncio.sleep(_POLL_INTERVAL)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
