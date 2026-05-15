from __future__ import annotations

import re
from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api", tags=["configs"])

_PROJECT_ROOT = Path(__file__).parent.parent.parent
_AIDER_YAML = _PROJECT_ROOT / "aider.yaml"
_CONFIG_DIR = _PROJECT_ROOT / "config"

# 允许操作的文件名格式（字母数字连字符下划线，.yaml 结尾），防止路径遍历
_SAFE_NAME = re.compile(r'^[\w\-]+\.yaml$')

# 各类型的测试默认值（供新建配置时自动填充）
_TYPE_DEFAULTS = {
    "python": {"cmd": "pytest tests/ -x -q", "framework": "pytest", "dir": "tests/", "cmd_dir": "", "stack_filter": ""},
    "java":   {"cmd": "mvn test -q --no-transfer-progress", "framework": "JUnit 5", "dir": "src/test/java/", "cmd_dir": "", "stack_filter": ""},
}


# ── 数据模型 ─────────────────────────────────────────────────────────────────

class AiderYaml(BaseModel):
    """全局 Aider 配置，对应 aider.yaml。"""
    model: str = "openai/claude-opus-4.7"
    api_base: str = ""
    api_key: str = ""
    context_tokens: int = 200000


class TestSection(BaseModel):
    cmd: str = "pytest tests/ -x -q"
    framework: str = "pytest"
    dir: str = "tests/"
    cmd_dir: str = ""
    stack_filter: str = ""


class GitSection(BaseModel):
    repo_url: str = ""
    clone_base_dir: str = r"D:\fixRepo"
    remote: str = "origin"
    base_branch: str = "main"
    github_token: str = ""


class ProjectConfig(BaseModel):
    """项目配置文件完整结构，存放于 config/ 目录。"""
    type: str = "python"   # python | java
    git: GitSection = GitSection()
    test: TestSection = TestSection()


# ── 工具函数 ─────────────────────────────────────────────────────────────────

def _safe_path(filename: str) -> Path:
    if not _SAFE_NAME.match(filename):
        raise HTTPException(status_code=400, detail="非法文件名")
    _CONFIG_DIR.mkdir(exist_ok=True)
    return _CONFIG_DIR / filename


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _dump_yaml(path: Path, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)


# ── aider.yaml 接口 ───────────────────────────────────────────────────────────

@router.get("/aider-config")
async def get_aider_config():
    """读取全局 aider.yaml。"""
    raw = _load_yaml(_AIDER_YAML)
    return AiderYaml(
        model=raw.get("model", "openai/claude-opus-4.7"),
        api_base=raw.get("api_base", ""),
        api_key=raw.get("api_key", ""),
        context_tokens=int(raw.get("context_tokens", 200000)),
    ).model_dump()


@router.put("/aider-config")
async def save_aider_config(body: AiderYaml):
    """保存全局 aider.yaml。"""
    _dump_yaml(_AIDER_YAML, {
        "model": body.model,
        "api_base": body.api_base,
        "api_key": body.api_key,
        "context_tokens": body.context_tokens,
    })
    return {"ok": True}


# ── 项目配置接口 ──────────────────────────────────────────────────────────────

@router.get("/configs")
async def list_configs():
    """列出 config/ 目录下所有项目配置文件。"""
    _CONFIG_DIR.mkdir(exist_ok=True)
    yamls = sorted(_CONFIG_DIR.glob("*.yaml"))
    return [{"name": f.name, "path": f.name} for f in yamls]


@router.get("/configs/defaults/{proj_type}")
async def get_type_defaults(proj_type: str):
    """返回指定类型的测试默认值。"""
    defaults = _TYPE_DEFAULTS.get(proj_type, _TYPE_DEFAULTS["python"])
    return defaults


@router.get("/configs/{filename}")
async def get_config(filename: str):
    """读取单个项目配置文件，返回结构化 JSON。"""
    path = _safe_path(filename)
    if not path.exists():
        raise HTTPException(status_code=404, detail="配置文件不存在")
    raw = _load_yaml(path)
    proj_type = raw.get("type", "python")
    td = _TYPE_DEFAULTS.get(proj_type, _TYPE_DEFAULTS["python"])
    git_raw = raw.get("git", {})
    test_raw = raw.get("test", {})
    return ProjectConfig(
        type=proj_type,
        git=GitSection(
            repo_url=git_raw.get("repo_url", ""),
            clone_base_dir=git_raw.get("clone_base_dir", r"D:\fixRepo"),
            remote=git_raw.get("remote", "origin"),
            base_branch=git_raw.get("base_branch", "main"),
            github_token=git_raw.get("github_token", ""),
        ),
        test=TestSection(
            cmd=test_raw.get("cmd", td["cmd"]),
            framework=test_raw.get("framework", td["framework"]),
            dir=test_raw.get("dir", td["dir"]),
            cmd_dir=test_raw.get("cmd_dir", ""),
            stack_filter=test_raw.get("stack_filter", ""),
        ),
    ).model_dump()


@router.put("/configs/{filename}")
async def save_config(filename: str, body: ProjectConfig):
    """保存项目配置文件（config/ 目录）。"""
    path = _safe_path(filename)
    git_dict: dict = {
        "repo_url": body.git.repo_url,
        "clone_base_dir": body.git.clone_base_dir,
        "remote": body.git.remote,
        "base_branch": body.git.base_branch,
    }
    if body.git.github_token:
        git_dict["github_token"] = body.git.github_token

    test_dict: dict = {
        "cmd": body.test.cmd,
        "framework": body.test.framework,
        "dir": body.test.dir,
    }
    if body.test.cmd_dir:
        test_dict["cmd_dir"] = body.test.cmd_dir
    if body.test.stack_filter:
        test_dict["stack_filter"] = body.test.stack_filter

    _dump_yaml(path, {"type": body.type, "git": git_dict, "test": test_dict})
    return {"ok": True}


@router.post("/configs")
async def create_config(body: ProjectConfig, filename: str = "new.yaml"):
    """新建项目配置文件（config/ 目录）。"""
    if not _SAFE_NAME.match(filename):
        raise HTTPException(status_code=400, detail="非法文件名")
    path = _CONFIG_DIR / filename
    if path.exists():
        raise HTTPException(status_code=409, detail="文件已存在")
    await save_config(filename, body)
    return {"ok": True, "filename": filename}


# ── 报告接口 ──────────────────────────────────────────────────────────────────

@router.get("/reports")
async def list_reports():
    report_base = _PROJECT_ROOT / "reports"
    if not report_base.exists():
        return []
    files = sorted(report_base.glob("*/report-*.md"), reverse=True)
    return [
        {"name": f"{f.parent.name} / {f.name}", "id": f"{f.parent.name}/{f.stem}"}
        for f in files
    ]


@router.get("/reports/{report_id:path}")
async def get_report(report_id: str):
    path = (_PROJECT_ROOT / "reports" / f"{report_id}.md")
    if not path.exists():
        raise HTTPException(status_code=404, detail="报告不存在")
    return {"content": path.read_text(encoding="utf-8")}
