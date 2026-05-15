from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from web.core.job_runner import JobRunner
from web.core.job_store import JobStore
from web.routers import configs, jobs, stream

_STATIC_DIR = Path(__file__).parent / "static"
_TEMPLATES_DIR = Path(__file__).parent / "templates"

templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


@asynccontextmanager
async def lifespan(app: FastAPI):
    store = JobStore()
    app.state.runner = JobRunner(store)
    yield


app = FastAPI(
    title="fix-bug Web UI",
    description="自动 Bug 修复工具可视化界面",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(jobs.router)
app.include_router(stream.router)
app.include_router(configs.router)

app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def index(request: Request):
    return templates.TemplateResponse(request, "base.html")
