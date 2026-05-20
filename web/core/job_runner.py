from __future__ import annotations

import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from src.aider_runner import AiderRunner
from src.config import load_config
from src.git_manager import GitManager, build_auth_url, ensure_aiderignore, ensure_repo
from src.module_resolver import inject_module_into_cmd, resolve_module
from src.notifier import notify_all
from src.pr_creator import create_review_request
from src.test_runner import TestRunner
from src.test_selector import narrow_test_cmd
from src.utils import filter_stack
from web.core.job_store import Job, JobStore

LOG_DIR = Path("reports") / "logs"


class JobCancelledError(Exception):
    """用户主动取消任务时抛出，用于从 _run() 中干净退出。

    参照 asyncio.CancelledError 的设计：用异常做流程控制，
    让 try/except 自动展开所有后续步骤，无需在每处手动检查标志位。
    """


class JobRunner:
    """任务执行引擎。

    使用单线程池保证同时只有一个 Aider 任务运行（避免 Git 冲突）。
    每个任务的日志行写入内存缓冲区，同时追加到磁盘日志文件，
    支持 SSE 端点实时读取或历史回放。
    """

    def __init__(self, store: JobStore):
        self.store = store
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._lock = threading.Lock()
        # 内存日志缓冲：job_id → [line, ...]
        self._buffers: dict[str, list[str]] = {}
        # 任务完成标志：job_id → bool
        self._done: dict[str, bool] = {}
        # 当前运行的 AiderRunner 实例（用于取消）
        self._current_aider: AiderRunner | None = None
        # 被手动取消的任务 ID 集合；_checkpoint() 据此决定是否抛出 JobCancelledError
        self._cancelled: set[str] = set()

    # ── 内部工具 ──────────────────────────────────────────────

    def _checkpoint(self, job_id: str) -> None:
        """取消检查点：若任务已被取消则抛出 JobCancelledError。

        在 _run() 的关键节点调用一次，异常会自动展开后续所有步骤，
        无需在每个分支重复判断标志位。
        """
        if job_id in self._cancelled:
            raise JobCancelledError(job_id)
        LOG_DIR.mkdir(parents=True, exist_ok=True)

    # ── 公开接口 ──────────────────────────────────────────────

    def submit(self, config_path: str, error_message: str) -> str:
        """提交新任务。已有任务运行中时抛出 RuntimeError。"""
        with self._lock:
            if self._has_running():
                raise RuntimeError("已有任务运行中，请等待完成后再提交")

        job_id = self.store.create(config_path)
        self._buffers[job_id] = []
        self._done[job_id] = False
        self._executor.submit(self._run, job_id, config_path, error_message)
        return job_id

    def get_lines(self, job_id: str, offset: int = 0) -> list[str]:
        """返回指定偏移量后的日志行（内存优先，内存中无则从磁盘读取）。"""
        if job_id in self._buffers:
            return self._buffers[job_id][offset:]
        log_file = LOG_DIR / f"{job_id}.log"
        if log_file.exists():
            lines = log_file.read_text(encoding="utf-8").splitlines()
            return lines[offset:]
        return []

    def delete_job(self, job_id: str) -> None:
        """删除任务记录及其磁盘日志文件。运行中的任务不允许删除。"""
        job = self.store.get(job_id)
        if job and job.status == "running":
            raise RuntimeError("运行中的任务不能删除，请先停止")
        self.store.delete(job_id)
        log_file = LOG_DIR / f"{job_id}.log"
        if log_file.exists():
            log_file.unlink()
        self._buffers.pop(job_id, None)
        self._done.pop(job_id, None)
        self._cancelled.discard(job_id)

    def cancel(self, job_id: str) -> None:
        """强制终止运行中的任务。"""
        # 先标记，再杀进程——_run() 检测到标记后不会再覆盖状态
        self._cancelled.add(job_id)
        if self._current_aider:
            self._current_aider.cancel()
        self.store.update(job_id, status="stopped", error_msg="用户手动停止",
                          finished_at=datetime.now().isoformat(timespec="seconds"))
        self._done[job_id] = True

    def is_done(self, job_id: str) -> bool:
        """任务是否已结束（成功/失败/不存在）。"""
        if job_id in self._done:
            return self._done[job_id]
        job = self.store.get(job_id)
        return job is None or job.status in ("success", "failed", "stopped")

    # ── 内部实现 ──────────────────────────────────────────────

    def _has_running(self) -> bool:
        return any(j.status == "running" for j in self.store.list_all())

    def _log(self, job_id: str, line: str) -> None:
        self._buffers.setdefault(job_id, []).append(line)
        log_file = LOG_DIR / f"{job_id}.log"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    @staticmethod
    def _fmt_duration(seconds: float) -> str:
        s = int(seconds)
        return f"{s // 60}m {s % 60:02d}s" if s >= 60 else f"{s}s"

    def _run(self, job_id: str, config_path: str, error_message: str) -> None:
        t0 = time.monotonic()
        self.store.update(job_id, status="running")
        log = lambda line: self._log(job_id, line)
        log(f"▶ 任务启动  id={job_id}")

        try:
            # config_path 来自前端，仅含文件名（如 python.yaml）；
            # load_config 需要相对于项目根目录的路径
            cfg_path = Path("config") / Path(config_path).name
            cfg = load_config(cfg_path)
            error_message = filter_stack(error_message, cfg.aider.stack_filter)

            # ── Step 1: 创建分支 ──────────────────────────────
            log("─" * 40)
            log("Step 1 · 创建分支")
            token = cfg.git.gitlab_token if cfg.git.platform == "gitlab" else cfg.git.github_token
            auth_url = build_auth_url(cfg.git.repo_url, cfg.git.platform, token)
            ensure_repo(cfg.git.repo_path, cfg.git.repo_url, auth_url, cfg.git.git_proxy)
            ensure_aiderignore(cfg.git.repo_path)
            git = GitManager(cfg.git.repo_path, cfg.git.remote, cfg.git.base_branch, cfg.git.git_proxy)
            branch_name = git.create_fix_branch()
            log(f"✓ 分支已创建: {branch_name}")
            self.store.update(job_id, branch=branch_name)

            # ── Step 2: Aider 修复 ────────────────────────────
            log("─" * 40)
            log("Step 2 · AI 修复")
            resolved_mod = resolve_module(cfg.git.repo_path, error_message, cfg.aider.stack_filter)
            effective_test_cmd = cfg.aider.test_cmd
            effective_test_dir = cfg.aider.test_dir
            if resolved_mod and resolved_mod.name != ".":
                effective_test_cmd = inject_module_into_cmd(effective_test_cmd, resolved_mod.name)
                if not effective_test_dir or effective_test_dir.strip("/") == "src/test/java":
                    effective_test_dir = resolved_mod.test_dir_with_package
                log(f"已定位模块: {resolved_mod.name}  测试目录: {effective_test_dir}")
            elif not effective_test_dir:
                effective_test_dir = "src/test/java/"

            aider = AiderRunner(
                repo_path=cfg.git.repo_path,
                model=cfg.aider.model,
                test_cmd=effective_test_cmd,
                test_framework=cfg.aider.test_framework,
                test_dir=effective_test_dir,
                cmd_dir=cfg.aider.cmd_dir,
                api_base=cfg.aider.api_base,
                api_key=cfg.aider.api_key,
                context_tokens=cfg.aider.context_tokens,
            )
            self._current_aider = aider
            fix_ok = aider.run(error_message, log_fn=log)
            self._current_aider = None

            # Aider 结束后立即检查是否被取消——若是，则抛出异常统一处理，
            # 无需在 if not fix_ok 及后续每个分支重复判断标志位
            self._checkpoint(job_id)

            if not fix_ok:
                log("✗ Aider 未能完成修复，流程终止")
                git.checkout_base()
                self.store.update(job_id, status="failed", error_msg="Aider 修复失败")
                return

            # ── Step 3: 验证测试 ──────────────────────────────
            log("─" * 40)
            log("Step 3 · 验证测试")
            new_tests = git.added_test_classes()
            if new_tests:
                verify_cmd = narrow_test_cmd(aider.test_cmd, new_tests)
                log(f"detected {len(new_tests)} new test class(es), narrowing verify cmd")
            else:
                verify_cmd = aider.test_cmd
                log("no new test class detected, fallback to full test_cmd")
            tester = TestRunner(cfg.git.repo_path, verify_cmd)
            test_passed, output = tester.run()

            if not test_passed:
                log("✗ 测试未通过，中止推送")
                for out_line in output[-3000:].splitlines():
                    log(out_line)
                notify_all(
                    branch_name=branch_name, pr_url="",
                    error_summary=error_message, test_passed=False,
                    project_name=cfg.git.repo_name,
                )
                self.store.update(job_id, status="failed", error_msg="测试验证失败")
                return
            log("✓ 测试全部通过")

            # ── Step 4: 推送分支 ──────────────────────────────
            log("─" * 40)
            log("Step 4 · 推送分支")
            has_new = git.has_commits_ahead()
            if has_new:
                git.push_branch()
                log("✓ 分支已推送")
            else:
                log("分支无新提交，跳过推送与 PR 创建")

            pr_url = ""
            if has_new:
                log("─" * 40)
                log("Step 5 · 创建 PR")
                try:
                    pr_url = create_review_request(cfg.git, branch_name, cfg.git.base_branch, error_message)
                    if pr_url:
                        log(f"✓ PR 已创建: {pr_url}")
                except Exception as exc:
                    log(f"PR 创建失败（可手动创建）: {exc}")
            self.store.update(job_id, pr_url=pr_url)

            # ── Step 6: 生成报告 ──────────────────────────────
            log("─" * 40)
            log("Step 6 · 生成报告")
            notify_all(
                branch_name=branch_name, pr_url=pr_url,
                error_summary=error_message, test_passed=True,
                project_name=cfg.git.repo_name,
            )
            log(f"✓ Markdown 报告已生成至 reports/{cfg.git.repo_name}/")

            elapsed = self._fmt_duration(time.monotonic() - t0)
            finished = datetime.now().isoformat(timespec="seconds")
            self.store.update(job_id, status="success", finished_at=finished)
            log("─" * 40)
            log(f"✅ 流程全部完成  用时 {elapsed}")

        except JobCancelledError:
            pass  # 状态已由 cancel() 写入，无需重复处理

        except Exception as exc:
            log(f"[错误] {exc}")
            for tb_line in traceback.format_exc().splitlines():
                log(tb_line)
            elapsed = self._fmt_duration(time.monotonic() - t0)
            log(f"用时 {elapsed}")
            finished = datetime.now().isoformat(timespec="seconds")
            self.store.update(job_id, status="failed", error_msg=str(exc), finished_at=finished)

        finally:
            self._current_aider = None
            self._done[job_id] = True
