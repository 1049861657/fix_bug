from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "jobs.db"


@dataclass
class Job:
    id: str
    config_path: str
    status: str       # pending | running | success | failed | stopped
    created_at: str   # 任务提交时间，也用于计算用时（finished_at - created_at）
    branch: str
    pr_url: str
    error_msg: str
    finished_at: str  # 任务结束时间（成功或失败）


class JobStore:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._init_db()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id          TEXT PRIMARY KEY,
                    config_path TEXT NOT NULL,
                    status      TEXT NOT NULL DEFAULT 'pending',
                    created_at  TEXT NOT NULL,
                    branch      TEXT NOT NULL DEFAULT '',
                    pr_url      TEXT NOT NULL DEFAULT '',
                    error_msg   TEXT NOT NULL DEFAULT '',
                    finished_at TEXT NOT NULL DEFAULT ''
                )
            """)

    def create(self, config_path: str) -> str:
        job_id = str(uuid.uuid4())
        now = datetime.now().isoformat(timespec="seconds")
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?)",
                (job_id, config_path, "pending", now, "", "", "", ""),
            )
        return job_id

    def update(self, job_id: str, **kwargs: str) -> None:
        set_clause = ", ".join(f"{k} = ?" for k in kwargs)
        with self._conn() as conn:
            conn.execute(
                f"UPDATE jobs SET {set_clause} WHERE id = ?",
                (*kwargs.values(), job_id),
            )

    def get(self, job_id: str) -> Job | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return Job(**dict(row)) if row else None

    def list_all(self) -> list[Job]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC"
            ).fetchall()
        return [Job(**dict(row)) for row in rows]

    def delete(self, job_id: str) -> bool:
        """从数据库删除任务记录，返回是否实际删除了一行。"""
        with self._conn() as conn:
            cursor = conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        return cursor.rowcount > 0
