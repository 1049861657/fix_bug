from __future__ import annotations

from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import os

from git import Repo
from rich.console import Console

console = Console()


def _proxy_env(proxy: str = "") -> dict:
    """构建代理环境变量字典，优先用显式传入的 proxy，否则透传系统环境变量。
    proxy 为空且系统无代理时返回空字典（不影响 git 全局配置）。
    """
    if proxy:
        return {
            "HTTP_PROXY": proxy, "HTTPS_PROXY": proxy,
            "http_proxy": proxy, "https_proxy": proxy,
        }
    proxy_keys = ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "NO_PROXY", "no_proxy"]
    return {k: os.environ[k] for k in proxy_keys if k in os.environ}


def build_auth_url(repo_url: str, platform: str, token: str) -> str:
    """将 token 嵌入 HTTPS URL，避免 clone/push 时交互式密码提示。
    SSH URL 或未提供 token 时原样返回。

    GitHub:  https://x-token-auth:{token}@github.com/org/repo.git
    GitLab:  https://oauth2:{token}@gitlab.company.com/group/repo.git
    """
    if not token or not repo_url.startswith("http"):
        return repo_url
    parsed = urlparse(repo_url)
    if platform == "gitlab":
        userinfo = f"oauth2:{token}"
    else:
        userinfo = f"x-token-auth:{token}"
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    netloc = f"{userinfo}@{host}"
    return urlunparse(parsed._replace(netloc=netloc))


def ensure_repo(repo_path: str, repo_url: str, auth_url: str = "", proxy: str = "") -> None:
    """若本地路径不存在则从 repo_url clone；已存在则跳过。
    auth_url 为带 token 的认证 URL（build_auth_url 生成），不传则回退到 repo_url。
    proxy 为代理地址（如 http://127.0.0.1:7897），内网仓库留空。
    """
    path = Path(repo_path).resolve()
    if path.exists() and (path / ".git").exists():
        return
    if not repo_url:
        raise ValueError(
            f"本地路径 {path} 不存在，且未配置 git.repo_url，无法自动 clone。"
        )
    clone_url = auth_url or repo_url
    console.print(f"[cyan]目录不存在，正在 clone: {repo_url} → {path}[/cyan]")
    path.mkdir(parents=True, exist_ok=True)
    env = _proxy_env(proxy) or None
    Repo.clone_from(clone_url, path, env=env)
    console.print(f"[green]✓ Clone 完成[/green]")


# 写入 .aiderignore 时使用的默认排除清单。
# 目标：把无关于源码逻辑的文件挡在 Aider repo-map 之外，让有限的 token 预算
# 集中在 src/main 与 src/test 等业务代码上。
# 设计原则：宁缺毋滥——只排除几乎所有项目都不需要的目录/文件，避免误伤。
_AIDERIGNORE_DEFAULT = """\
# fix-bug 自动写入：缩小 Aider repo-map 的扫描面，提升关键文件被纳入的概率。
# 用户可以删掉或自行编辑此文件；只要文件存在，fix-bug 就不会覆盖。

# IDE / Cursor / 各类 AI 工具的元数据
.cursor/
.idea/
.vscode/
.fitten/
.specs/
.vercel/

# 构建产物
target/
build/
out/
dist/
.gradle/

# 依赖目录
node_modules/
.venv/
venv/

# 锁文件与大型生成文件（对源码逻辑无贡献）
*.lock
*.lockb
package-lock.json
pnpm-lock.yaml
yarn.lock
uv.lock

# 二进制资源
*.jar
*.war
*.class
*.zip
*.tar.gz
*.png
*.jpg
*.jpeg
*.gif
*.svg
*.pdf

# Aider 自己的缓存（防御性，正常情况下 aider 会自动忽略）
.aider.tags.cache.*/
.aider.chat.history.*
.aider.input.history
"""


def ensure_aiderignore(repo_path: str) -> None:
    """确保仓库根目录存在 .aiderignore，缺失时写入默认排除清单。

    Aider 用此文件控制 repo-map 扫描范围；clone 后写入一次，之后用户可手动编辑，
    本函数检测到文件存在则不覆盖（尊重用户的本地修改）。
    """
    path = Path(repo_path).resolve() / ".aiderignore"
    if path.exists():
        return
    try:
        path.write_text(_AIDERIGNORE_DEFAULT, encoding="utf-8")
        console.print(f"[dim]已写入 .aiderignore 收敛 repo-map 范围: {path.name}[/dim]")
    except OSError as exc:
        console.print(f"[yellow]写入 .aiderignore 失败（不影响主流程）: {exc}[/yellow]")


class GitManager:
    def __init__(self, repo_path: str, remote: str, base_branch: str, proxy: str = ""):
        self.repo = Repo(Path(repo_path).resolve())
        self.remote = remote
        self.base_branch = base_branch
        self.branch_name: str = ""
        self._proxy = proxy

    def create_fix_branch(self) -> str:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.branch_name = f"fix/auto-{timestamp}"

        origin = self.repo.remotes[self.remote]
        console.print(f"[cyan]正在拉取最新代码 ({self.base_branch})...[/cyan]")
        with self.repo.git.custom_environment(**_proxy_env(self._proxy)):
            origin.fetch()

        # 优先用远程分支作为起点，远程不存在时回退到本地分支
        remote_ref = f"{self.remote}/{self.base_branch}"
        try:
            base_ref = self.repo.commit(remote_ref)
            console.print(f"[dim]基准: {remote_ref}[/dim]")
        except Exception:
            console.print(f"[yellow]远程 {remote_ref} 不存在，回退到本地 {self.base_branch}[/yellow]")
            base_ref = self.repo.heads[self.base_branch].commit

        new_branch = self.repo.create_head(self.branch_name, base_ref)
        new_branch.checkout()

        console.print(f"[green]✓ 已切换到新分支: {self.branch_name}[/green]")
        return self.branch_name

    def push_branch(self) -> None:
        console.print(f"[cyan]正在推送分支 {self.branch_name}...[/cyan]")
        with self.repo.git.custom_environment(**_proxy_env(self._proxy)):
            self.repo.remotes[self.remote].push(
                refspec=f"refs/heads/{self.branch_name}:refs/heads/{self.branch_name}",
            )
        console.print(f"[green]✓ 分支已推送[/green]")

    def has_commits_ahead(self) -> bool:
        """当前分支是否有领先于远程基准分支的提交（aider auto-commit 后工作区是干净的）"""
        try:
            base = self.repo.commit(f"{self.remote}/{self.base_branch}")
            ahead = list(self.repo.iter_commits(f"{self.remote}/{self.base_branch}..HEAD"))
            return len(ahead) > 0
        except Exception:
            return self.repo.is_dirty(untracked_files=True)

    def added_test_classes(self, test_suffix: str = "Test.java") -> list[str]:
        """提取本分支相对基准分支新增（或修改）的 Java 测试类全限定名。

        用于将 Step 3 的验证命令窄化到 AI 实际写过的测试上，避免被仓库里
        预先存在的脏测试（依赖 Nacos/Spring 上下文等）干扰。

        遍历 `origin/<base>..HEAD` 的 name-status diff，筛选状态为 A（新增）
        或 M（修改）、路径含 `src/test/java/` 且以 test_suffix 结尾的文件，
        将其相对路径转换成 Java 全限定类名。

        Returns:
            按出现顺序去重的全限定类名列表；解析失败或无新增测试时返回空。
        """
        ref = f"{self.remote}/{self.base_branch}"
        try:
            raw = self.repo.git.diff("--name-status", f"{ref}..HEAD")
        except Exception:
            return []

        result: list[str] = []
        seen: set[str] = set()
        for line in raw.splitlines():
            parts = line.split("\t", 1)
            if len(parts) != 2:
                continue
            status, path = parts[0].strip(), parts[1].strip().replace("\\", "/")
            if status[:1] not in ("A", "M"):
                continue
            if not path.endswith(test_suffix):
                continue
            marker = "src/test/java/"
            idx = path.find(marker)
            if idx < 0:
                continue
            rel = path[idx + len(marker):].removesuffix(".java")
            fqcn = rel.replace("/", ".")
            if fqcn and fqcn not in seen:
                seen.add(fqcn)
                result.append(fqcn)
        return result

    def checkout_base(self) -> None:
        self.repo.heads[self.base_branch].checkout()
