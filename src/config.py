from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()


@dataclass
class AiderConfig:
    model: str = "openai/claude-opus-4.7"
    test_cmd: str = "pytest tests/ -x -q"
    api_base: str = field(default_factory=lambda: os.getenv("FIX_BUG_API_BASE", ""))
    api_key: str = field(default_factory=lambda: os.getenv("FIX_BUG_API_KEY", ""))
    context_tokens: int = 200000


@dataclass
class GitConfig:
    repo_url: str = ""
    clone_base_dir: str = r"D:\fixRepo"
    remote: str = "origin"
    base_branch: str = "main"

    @property
    def repo_path(self) -> str:
        """从 repo_url 提取项目名，拼成本地路径。"""
        if not self.repo_url:
            return "."
        name = self.repo_url.rstrip("/").split("/")[-1]
        if name.endswith(".git"):
            name = name[:-4]
        return str(Path(self.clone_base_dir) / name)


@dataclass
class GitHubConfig:
    repo_slug: str = ""
    token: str = field(default_factory=lambda: os.getenv("GITHUB_TOKEN", ""))


@dataclass
class AppConfig:
    aider: AiderConfig = field(default_factory=AiderConfig)
    git: GitConfig = field(default_factory=GitConfig)
    github: GitHubConfig = field(default_factory=GitHubConfig)


def load_config(path: str | Path = "config.yaml") -> AppConfig:
    config_path = Path(path)
    if not config_path.exists():
        return AppConfig()

    with open(config_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    aider_raw = raw.get("aider", {})
    git_raw = raw.get("git", {})
    github_raw = raw.get("github", {})

    github_token = os.getenv(github_raw.get("token_env", "GITHUB_TOKEN"), "")

    return AppConfig(
        aider=AiderConfig(
            model=aider_raw.get("model", "openai/claude-opus-4.7"),
            test_cmd=aider_raw.get("test_cmd", "pytest tests/ -x -q"),
            api_base=os.getenv(aider_raw.get("api_base_env", "FIX_BUG_API_BASE"), ""),
            api_key=os.getenv(aider_raw.get("api_key_env", "FIX_BUG_API_KEY"), ""),
            context_tokens=int(aider_raw.get("context_tokens", 200000)),
        ),
        git=GitConfig(
            repo_url=git_raw.get("repo_url", ""),
            clone_base_dir=git_raw.get("clone_base_dir", r"D:\fixRepo"),
            remote=git_raw.get("remote", "origin"),
            base_branch=git_raw.get("base_branch", "main"),
        ),
        github=GitHubConfig(
            repo_slug=github_raw.get("repo_slug", ""),
            token=github_token,
        ),
    )
