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
    test_framework: str = "pytest"
    test_dir: str = "tests/"
    cmd_dir: str = ""
    stack_filter: str = ""  # 应用包名前缀，过滤堆栈噪音（如 com.example 或 app.）
    api_base: str = field(default_factory=lambda: os.getenv("FIX_BUG_API_BASE", ""))
    api_key: str = field(default_factory=lambda: os.getenv("FIX_BUG_API_KEY", ""))
    context_tokens: int = 200000


@dataclass
class GitConfig:
    repo_url: str = ""
    clone_base_dir: str = r"D:\fixRepo"
    remote: str = "origin"
    base_branch: str = "main"
    github_token: str = field(default_factory=lambda: os.getenv("GITHUB_TOKEN", ""))

    @property
    def repo_name(self) -> str:
        """从 repo_url 提取仓库名，如 https://github.com/x/bug_java → bug_java。"""
        if not self.repo_url:
            return "default"
        return self.repo_url.rstrip("/").removesuffix(".git").split("/")[-1]

    @property
    def repo_path(self) -> str:
        if not self.repo_url:
            return "."
        return str(Path(self.clone_base_dir) / self.repo_name)

    @property
    def repo_slug(self) -> str:
        parts = self.repo_url.rstrip("/").removesuffix(".git").split("/")
        return f"{parts[-2]}/{parts[-1]}" if len(parts) >= 2 else ""


@dataclass
class AppConfig:
    aider: AiderConfig = field(default_factory=AiderConfig)
    git: GitConfig = field(default_factory=GitConfig)


def load_config(path: str | Path = "config.yaml") -> AppConfig:
    config_path = Path(path)
    if not config_path.exists():
        return AppConfig()

    with open(config_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    aider_raw = raw.get("aider", {})
    git_raw = raw.get("git", {})
    github_token_env = raw.get("github", {}).get("token_env", "GITHUB_TOKEN")

    return AppConfig(
        aider=AiderConfig(
            model=aider_raw.get("model", "openai/claude-opus-4.7"),
            test_cmd=aider_raw.get("test_cmd", "pytest tests/ -x -q"),
            test_framework=aider_raw.get("test_framework", "pytest"),
            test_dir=aider_raw.get("test_dir", "tests/"),
            cmd_dir=aider_raw.get("cmd_dir", ""),
            stack_filter=aider_raw.get("stack_filter", ""),
            api_base=os.getenv(aider_raw.get("api_base_env", "FIX_BUG_API_BASE"), ""),
            api_key=os.getenv(aider_raw.get("api_key_env", "FIX_BUG_API_KEY"), ""),
            context_tokens=int(aider_raw.get("context_tokens", 200000)),
        ),
        git=GitConfig(
            repo_url=git_raw.get("repo_url", ""),
            clone_base_dir=git_raw.get("clone_base_dir", r"D:\fixRepo"),
            remote=git_raw.get("remote", "origin"),
            base_branch=git_raw.get("base_branch", "main"),
            github_token=os.getenv(github_token_env, ""),
        ),
    )
