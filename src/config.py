from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import yaml

_AIDER_YAML = Path("aider.yaml")
_CONFIG_DIR = Path("config")


@dataclass
class AiderConfig:
    model: str = "claude-opus-4.7"
    api_base: str = ""
    api_key: str = ""
    context_tokens: int = 200000
    test_cmd: str = "pytest tests/ -x -q"
    test_framework: str = "pytest"
    test_dir: str = "tests/"
    cmd_dir: str = ""
    stack_filter: str = ""
    java_home: str = ""   # 指定 JDK 路径，留空使用系统默认


# 各语言的测试默认值，供 load_config 在 test 节缺省时使用
# 注意 dir 留空：多模块项目由 module_resolver 推导为 <module>/src/test/java/；
# 单模块由 main 流程兜底为 src/test/java/
_TYPE_DEFAULTS: dict[str, dict] = {
    "python": {"cmd": "pytest tests/ -x -q", "framework": "pytest", "dir": "tests/"},
    "java":   {"cmd": "mvn test -q --no-transfer-progress", "framework": "JUnit 5", "dir": ""},
}


@dataclass
class GitConfig:
    repo_url: str = ""
    clone_base_dir: str = r"D:\fixRepo"
    remote: str = "origin"
    base_branch: str = "main"
    # platform: "github" | "gitlab"
    platform: str = "github"
    github_token: str = ""
    # GitLab 专用字段
    gitlab_token: str = ""
    # 代理地址（仅需访问外网的仓库填写，如 GitHub；内网 GitLab 留空）
    git_proxy: str = ""

    @property
    def repo_name(self) -> str:
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
        """返回仓库路径（去掉 host 部分）。
        GitHub:  https://github.com/org/repo      → org/repo
        GitLab EE: https://gitlab.co/g/sub/repo  → g/sub/repo
        SSH:     git@host:group/sub/repo.git      → group/sub/repo
        """
        url = self.repo_url.rstrip("/").removesuffix(".git")
        if not url:
            return ""
        try:
            parsed = urlparse(url)
            if parsed.scheme in ("http", "https"):
                return parsed.path.lstrip("/")
            # SSH 格式：git@host:path
            if ":" in url:
                return url.split(":", 1)[-1]
        except Exception:
            pass
        parts = url.split("/")
        return f"{parts[-2]}/{parts[-1]}" if len(parts) >= 2 else ""


@dataclass
class AppConfig:
    aider: AiderConfig = field(default_factory=AiderConfig)
    git: GitConfig = field(default_factory=GitConfig)


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_aider_yaml(path: str | Path = _AIDER_YAML) -> dict:
    """加载全局 Aider 配置（model / api_base / api_key / context_tokens）。"""
    return _load_yaml(Path(path))


def load_config(path: str | Path = _CONFIG_DIR / "python.yaml",
                aider_path: str | Path = _AIDER_YAML) -> AppConfig:
    """
    加载配置，分两个文件：
      - aider_path（默认 aider.yaml）：AI 模型全局配置
      - path（项目配置，默认 config/python.yaml）：git 仓库 + 测试设置
    """
    aider_raw = _load_yaml(Path(aider_path))
    proj_raw = _load_yaml(Path(path))

    git_raw = proj_raw.get("git", {})
    test_raw = proj_raw.get("test", {})
    proj_type = proj_raw.get("type", "python")
    type_defaults = _TYPE_DEFAULTS.get(proj_type, _TYPE_DEFAULTS["python"])

    return AppConfig(
        aider=AiderConfig(
            model=aider_raw.get("model", "claude-opus-4.7"),
            api_base=aider_raw.get("api_base", ""),
            api_key=aider_raw.get("api_key", ""),
            context_tokens=int(aider_raw.get("context_tokens", 200000)),
            test_cmd=test_raw.get("cmd", type_defaults["cmd"]),
            test_framework=test_raw.get("framework", type_defaults["framework"]),
            test_dir=test_raw.get("dir", type_defaults["dir"]),
            cmd_dir=test_raw.get("cmd_dir", ""),
            stack_filter=test_raw.get("stack_filter", ""),
        ),
        git=GitConfig(
            repo_url=git_raw.get("repo_url", ""),
            clone_base_dir=git_raw.get("clone_base_dir", r"D:\fixRepo"),
            remote=git_raw.get("remote", "origin"),
            base_branch=git_raw.get("base_branch", "main"),
            platform=git_raw.get("platform", "github"),
            github_token=git_raw.get("github_token", ""),
            gitlab_token=git_raw.get("gitlab_token", ""),
            git_proxy=git_raw.get("git_proxy", ""),
        ),
    )
