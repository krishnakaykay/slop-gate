"""Async SQLite (WAL mode) session & revision repository with periodic TTL cleanup."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

import aiosqlite

from app.config import settings
from app.schemas.document import PageArtifact, RevisionDiff
from app.schemas.gate1 import Gate1Report, IssueDisposition


SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=5000;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    latest_revision INTEGER NOT NULL DEFAULT 1,
    active_run_count INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    last_accessed_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS revisions (
    session_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    filename TEXT NOT NULL,
    pdf_path TEXT NOT NULL,
    page_count INTEGER NOT NULL,
    detected_format TEXT NOT NULL,
    format_confidence TEXT NOT NULL,
    ghost_deck_mode TEXT NOT NULL,
    pages_json TEXT NOT NULL,
    diff_json TEXT,
    created_at REAL NOT NULL,
    PRIMARY KEY (session_id, revision),
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS gate1_runs (
    run_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    status TEXT NOT NULL,
    stage TEXT NOT NULL,
    config_json TEXT NOT NULL,
    report_json TEXT,
    error_message TEXT,
    created_at REAL NOT NULL,
    completed_at REAL,
    FOREIGN KEY (session_id, revision) REFERENCES revisions(session_id, revision) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS readthrough_state (
    session_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    reviewed_pages_json TEXT NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY (session_id, revision),
    FOREIGN KEY (session_id, revision) REFERENCES revisions(session_id, revision) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS gate2_sessions (
    session_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    mode TEXT NOT NULL,
    questions_json TEXT NOT NULL,
    answers_json TEXT NOT NULL,
    preserved_count INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL,
    PRIMARY KEY (session_id, revision),
    FOREIGN KEY (session_id, revision) REFERENCES revisions(session_id, revision) ON DELETE CASCADE
);

-- Fingerprint-indexed verified Gate 2 answers for v1 -> v2 preservation across revisions
CREATE TABLE IF NOT EXISTS gate2_answers (
    answer_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    source_revision INTEGER NOT NULL,
    page_fingerprints_json TEXT NOT NULL,
    question_json TEXT NOT NULL,
    answer_text TEXT NOT NULL,
    feedback TEXT NOT NULL DEFAULT '',
    verified INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);

-- Durable behavioral & error telemetry (intentionally decoupled from sessions TTL)
CREATE TABLE IF NOT EXISTS telemetry_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL NOT NULL,
    severity TEXT NOT NULL,
    event TEXT NOT NULL,
    source TEXT NOT NULL,
    session_id TEXT,
    revision INTEGER,
    stage TEXT,
    user_hash TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_telemetry_created ON telemetry_events(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_telemetry_rate ON telemetry_events(event, user_hash, created_at);

-- 1-click user feedback capture
CREATE TABLE IF NOT EXISTS user_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    session_id TEXT,
    revision INTEGER,
    stage TEXT NOT NULL DEFAULT 'unknown',
    user_hash TEXT,
    rating TEXT NOT NULL,
    tags_json TEXT NOT NULL DEFAULT '[]',
    comment TEXT NOT NULL DEFAULT '',
    context_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_feedback_created ON user_feedback(created_at DESC);
"""


class SessionStore:
    def __init__(self, db_path: Path | None = None, sessions_dir: Path | None = None) -> None:
        self.db_path = db_path or settings.db_path
        self.sessions_dir = sessions_dir or settings.sessions_dir
        self._init_lock = asyncio.Lock()
        self._initialized = False

    async def init(self) -> None:
        async with self._init_lock:
            if self._initialized:
                return
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self.sessions_dir.mkdir(parents=True, exist_ok=True)
            async with aiosqlite.connect(self.db_path) as db:
                await db.executescript(SCHEMA_SQL)
                # Idempotent migration for DBs created in Phase 1 before `feedback` column existed
                async with db.execute("PRAGMA table_info(gate2_answers)") as cur:
                    cols = {row[1] for row in await cur.fetchall()}
                if "feedback" not in cols:
                    await db.execute("ALTER TABLE gate2_answers ADD COLUMN feedback TEXT NOT NULL DEFAULT ''")
                await db.commit()
            self._initialized = True

    def _connect(self) -> aiosqlite.Connection:
        return aiosqlite.connect(self.db_path)

    def revision_dir(self, session_id: str, revision: int) -> Path:
        return self.sessions_dir / session_id / f"rev_{revision}"

    def stamped_pdf_path(self, session_id: str, revision: int) -> Path:
        return self.revision_dir(session_id, revision) / "stamped.pdf"

    async def touch_session(self, session_id: str) -> None:
        async with self._connect() as db:
            await db.execute("PRAGMA busy_timeout=5000;")
            await db.execute(
                "UPDATE sessions SET last_accessed_at = ? WHERE session_id = ?",
                (time.time(), session_id),
            )
            await db.commit()

    async def create_session_with_revision(
        self,
        *,
        session_id: str,
        filename: str,
        pdf_path: Path,
        page_count: int,
        detected_format: str,
        format_confidence: str,
        ghost_deck_mode: str,
        pages: list[PageArtifact],
    ) -> int:
        now = time.time()
        pages_json = json.dumps([p.model_dump() for p in pages])
        async with self._connect() as db:
            await db.execute("PRAGMA foreign_keys=ON;")
            await db.execute("PRAGMA busy_timeout=5000;")
            await db.execute(
                """
                INSERT INTO sessions (session_id, filename, latest_revision, active_run_count, created_at, last_accessed_at)
                VALUES (?, ?, 1, 0, ?, ?)
                """,
                (session_id, filename, now, now),
            )
            await db.execute(
                """
                INSERT INTO revisions (
                    session_id, revision, filename, pdf_path, page_count,
                    detected_format, format_confidence, ghost_deck_mode,
                    pages_json, diff_json, created_at
                ) VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
                """,
                (
                    session_id,
                    filename,
                    str(pdf_path),
                    page_count,
                    detected_format,
                    format_confidence,
                    ghost_deck_mode,
                    pages_json,
                    now,
                ),
            )
            await db.execute(
                """
                INSERT INTO readthrough_state (session_id, revision, reviewed_pages_json, updated_at)
                VALUES (?, 1, '[]', ?)
                """,
                (session_id, now),
            )
            await db.commit()
        return 1

    async def add_revision(
        self,
        *,
        session_id: str,
        revision: int,
        filename: str,
        pdf_path: Path,
        page_count: int,
        detected_format: str,
        format_confidence: str,
        ghost_deck_mode: str,
        pages: list[PageArtifact],
        diff: RevisionDiff,
        preserved_reviewed_pages: list[int],
    ) -> int:
        now = time.time()
        pages_json = json.dumps([p.model_dump() for p in pages])
        diff_json = json.dumps(diff.model_dump())
        async with self._connect() as db:
            await db.execute("PRAGMA foreign_keys=ON;")
            await db.execute("PRAGMA busy_timeout=5000;")
            await db.execute(
                """
                UPDATE sessions
                SET filename = ?, latest_revision = ?, last_accessed_at = ?
                WHERE session_id = ?
                """,
                (filename, revision, now, session_id),
            )
            await db.execute(
                """
                INSERT INTO revisions (
                    session_id, revision, filename, pdf_path, page_count,
                    detected_format, format_confidence, ghost_deck_mode,
                    pages_json, diff_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    revision,
                    filename,
                    str(pdf_path),
                    page_count,
                    detected_format,
                    format_confidence,
                    ghost_deck_mode,
                    pages_json,
                    diff_json,
                    now,
                ),
            )
            await db.execute(
                """
                INSERT OR REPLACE INTO readthrough_state (session_id, revision, reviewed_pages_json, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, revision, json.dumps(sorted(set(preserved_reviewed_pages))), now),
            )
            await db.commit()
        return revision

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)) as cur:
                row = await cur.fetchone()
                return dict(row) if row else None

    async def get_revision(self, session_id: str, revision: int | None = None) -> dict[str, Any] | None:
        sess = await self.get_session(session_id)
        if not sess:
            return None
        rev = revision if revision is not None else int(sess["latest_revision"])
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM revisions WHERE session_id = ? AND revision = ?",
                (session_id, rev),
            ) as cur:
                row = await cur.fetchone()
                if not row:
                    return None
                data = dict(row)
                data["pages"] = [PageArtifact.model_validate(p) for p in json.loads(data["pages_json"])]
                data["diff"] = RevisionDiff.model_validate(json.loads(data["diff_json"])) if data["diff_json"] else None
                return data

    async def create_gate1_run(self, *, session_id: str, revision: int, config: dict[str, Any]) -> str:
        run_id = uuid.uuid4().hex[:12]
        now = time.time()
        async with self._connect() as db:
            await db.execute("PRAGMA foreign_keys=ON;")
            await db.execute("PRAGMA busy_timeout=5000;")
            await db.execute(
                """
                INSERT INTO gate1_runs (run_id, session_id, revision, status, stage, config_json, created_at)
                VALUES (?, ?, ?, 'queued', 'queued', ?, ?)
                """,
                (run_id, session_id, revision, json.dumps(config), now),
            )
            await db.execute(
                "UPDATE sessions SET active_run_count = active_run_count + 1, last_accessed_at = ? WHERE session_id = ?",
                (now, session_id),
            )
            await db.commit()
        return run_id

    async def update_gate1_run(
        self,
        run_id: str,
        *,
        status: str | None = None,
        stage: str | None = None,
        report: Gate1Report | None = None,
        error_message: str | None = None,
        decrement_active: bool = False,
    ) -> None:
        now = time.time()
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            await db.execute("PRAGMA busy_timeout=5000;")
            async with db.execute("SELECT session_id FROM gate1_runs WHERE run_id = ?", (run_id,)) as cur:
                row = await cur.fetchone()
            if not row:
                return
            session_id = row["session_id"]

            fields: list[str] = []
            vals: list[Any] = []
            if status is not None:
                fields.append("status = ?")
                vals.append(status)
            if stage is not None:
                fields.append("stage = ?")
                vals.append(stage)
            if report is not None:
                fields.append("report_json = ?")
                vals.append(report.model_dump_json())
                fields.append("completed_at = ?")
                vals.append(now)
            if error_message is not None:
                fields.append("error_message = ?")
                vals.append(error_message)
                fields.append("completed_at = ?")
                vals.append(now)

            if fields:
                vals.append(run_id)
                await db.execute(f"UPDATE gate1_runs SET {', '.join(fields)} WHERE run_id = ?", vals)

            if decrement_active:
                await db.execute(
                    "UPDATE sessions SET active_run_count = MAX(0, active_run_count - 1), last_accessed_at = ? WHERE session_id = ?",
                    (now, session_id),
                )
            await db.commit()

    async def get_gate1_run(self, run_id: str) -> dict[str, Any] | None:
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM gate1_runs WHERE run_id = ?", (run_id,)) as cur:
                row = await cur.fetchone()
                if not row:
                    return None
                data = dict(row)
                data["config"] = json.loads(data["config_json"])
                data["report"] = Gate1Report.model_validate_json(data["report_json"]) if data["report_json"] else None
                return data

    async def get_latest_gate1_report(self, session_id: str, revision: int | None = None) -> Gate1Report | None:
        rev_data = await self.get_revision(session_id, revision)
        if not rev_data:
            return None
        rev = rev_data["revision"]
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT report_json FROM gate1_runs
                WHERE session_id = ? AND revision = ? AND status = 'completed' AND report_json IS NOT NULL
                ORDER BY created_at DESC LIMIT 1
                """,
                (session_id, rev),
            ) as cur:
                row = await cur.fetchone()
                if not row:
                    return None
                return Gate1Report.model_validate_json(row["report_json"])

    async def update_issue_disposition(
        self,
        *,
        run_id: str,
        issue_id: str,
        disposition: IssueDisposition | None,
    ) -> Gate1Report | None:
        from app.services.gate1_engine import compute_verdict, build_page_summaries

        run = await self.get_gate1_run(run_id)
        if not run or not run["report"]:
            return None
        report: Gate1Report = run["report"]
        found = False
        for issue in report.issues:
            if issue.id == issue_id:
                issue.disposition = disposition
                found = True
                break
        if not found:
            return None

        # Recompute verdict and page summaries deterministically
        report.verdict = compute_verdict(report.issues)
        word_counts = {p.page_number: p.word_count for p in report.pages}
        report.pages = build_page_summaries(len(report.pages), word_counts, report.issues)
        await self.update_gate1_run(run_id, report=report)
        return report

    async def update_creator_intent(self, *, run_id: str, creator_intent: str) -> Gate1Report | None:
        run = await self.get_gate1_run(run_id)
        if not run:
            return None
        cfg = run["config"]
        cfg["creator_intent"] = creator_intent
        report: Gate1Report | None = run["report"]
        async with self._connect() as db:
            await db.execute("PRAGMA busy_timeout=5000;")
            if report is not None:
                report.creator_intent = creator_intent
                await db.execute(
                    "UPDATE gate1_runs SET config_json = ?, report_json = ? WHERE run_id = ?",
                    (json.dumps(cfg), report.model_dump_json(), run_id),
                )
            else:
                await db.execute(
                    "UPDATE gate1_runs SET config_json = ? WHERE run_id = ?",
                    (json.dumps(cfg), run_id),
                )
            await db.commit()
        return report

    async def get_reviewed_pages(self, session_id: str, revision: int) -> list[int]:
        async with self._connect() as db:
            async with db.execute(
                "SELECT reviewed_pages_json FROM readthrough_state WHERE session_id = ? AND revision = ?",
                (session_id, revision),
            ) as cur:
                row = await cur.fetchone()
                return json.loads(row[0]) if row else []

    async def set_reviewed_pages(self, session_id: str, revision: int, reviewed_pages: list[int]) -> list[int]:
        cleaned = sorted(set(int(p) for p in reviewed_pages if int(p) >= 1))
        now = time.time()
        async with self._connect() as db:
            await db.execute("PRAGMA busy_timeout=5000;")
            await db.execute(
                """
                INSERT OR REPLACE INTO readthrough_state (session_id, revision, reviewed_pages_json, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, revision, json.dumps(cleaned), now),
            )
            await db.commit()
        return cleaned

    async def get_gate2_session(self, session_id: str, revision: int) -> dict[str, Any] | None:
        from app.schemas.gate2 import Gate2AnswerRecord, Gate2Question

        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM gate2_sessions WHERE session_id = ? AND revision = ?",
                (session_id, revision),
            ) as cur:
                row = await cur.fetchone()
                if not row:
                    return None
                data = dict(row)
                data["questions"] = [Gate2Question.model_validate(q) for q in json.loads(data["questions_json"])]
                raw_ans = json.loads(data["answers_json"])
                data["answers"] = {k: Gate2AnswerRecord.model_validate(v) for k, v in raw_ans.items()}
                return data

    async def save_gate2_session(
        self,
        *,
        session_id: str,
        revision: int,
        mode: str,
        questions: list[Any],
        answers: dict[str, Any],
        preserved_count: int = 0,
    ) -> None:
        now = time.time()
        q_json = json.dumps([q.model_dump() for q in questions])
        a_json = json.dumps({k: v.model_dump() for k, v in answers.items()})
        async with self._connect() as db:
            await db.execute("PRAGMA foreign_keys=ON;")
            await db.execute("PRAGMA busy_timeout=5000;")
            await db.execute(
                """
                INSERT OR REPLACE INTO gate2_sessions (
                    session_id, revision, mode, questions_json, answers_json, preserved_count, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (session_id, revision, mode, q_json, a_json, preserved_count, now),
            )
            await db.execute(
                "UPDATE sessions SET last_accessed_at = ? WHERE session_id = ?",
                (now, session_id),
            )
            await db.commit()

    async def upsert_verified_gate2_answer(
        self,
        *,
        session_id: str,
        source_revision: int,
        question: Any,
        answer_text: str,
        feedback: str,
    ) -> None:
        now = time.time()
        ans_id = f"{session_id}:{source_revision}:{question.id}"
        async with self._connect() as db:
            await db.execute("PRAGMA foreign_keys=ON;")
            await db.execute("PRAGMA busy_timeout=5000;")
            await db.execute(
                """
                INSERT OR REPLACE INTO gate2_answers (
                    answer_id, session_id, source_revision, page_fingerprints_json,
                    question_json, answer_text, feedback, verified, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    ans_id,
                    session_id,
                    source_revision,
                    json.dumps(question.page_fingerprints),
                    json.dumps(question.model_dump()),
                    answer_text,
                    feedback,
                    now,
                ),
            )
            await db.commit()

    async def list_verified_gate2_answers(self, session_id: str) -> list[dict[str, Any]]:
        from app.schemas.gate2 import Gate2Question

        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT * FROM gate2_answers
                WHERE session_id = ? AND verified = 1
                ORDER BY source_revision DESC, answer_id ASC
                """,
                (session_id,),
            ) as cur:
                rows = await cur.fetchall()
                out: list[dict[str, Any]] = []
                for r in rows:
                    d = dict(r)
                    d["page_fingerprints"] = json.loads(d["page_fingerprints_json"])
                    d["question"] = Gate2Question.model_validate(json.loads(d["question_json"]))
                    out.append(d)
                return out

    async def sweep_expired_sessions(self, ttl_hours: int | None = None) -> int:
        cutoff = time.time() - (ttl_hours or settings.session_ttl_hours) * 3600
        expired_ids: list[str] = []
        async with self._connect() as db:
            await db.execute("PRAGMA foreign_keys=ON;")
            await db.execute("PRAGMA busy_timeout=5000;")
            async with db.execute(
                "SELECT session_id FROM sessions WHERE last_accessed_at < ? AND active_run_count = 0",
                (cutoff,),
            ) as cur:
                expired_ids = [row[0] for row in await cur.fetchall()]
            for sid in expired_ids:
                await db.execute("DELETE FROM sessions WHERE session_id = ?", (sid,))
            await db.commit()

        for sid in expired_ids:
            shutil.rmtree(self.sessions_dir / sid, ignore_errors=True)
        return len(expired_ids)

    # ------------------------------------------------------------------
    # Telemetry & 1-Click Feedback Storage
    # ------------------------------------------------------------------
    async def record_telemetry_event(
        self,
        *,
        severity: str,
        event: str,
        source: str,
        session_id: str | None = None,
        revision: int | None = None,
        stage: str | None = None,
        user_hash: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> int:
        now = time.time()
        async with self._connect() as db:
            await db.execute("PRAGMA busy_timeout=5000;")
            cur = await db.execute(
                """
                INSERT INTO telemetry_events (
                    created_at, severity, event, source, session_id, revision, stage, user_hash, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now,
                    severity,
                    event,
                    source,
                    session_id,
                    revision,
                    stage,
                    user_hash,
                    json.dumps(payload or {}, default=str),
                ),
            )
            await db.commit()
            return int(cur.lastrowid or 0)

    async def count_recent_events(self, *, event: str, user_hash: str, since_ts: float) -> int:
        async with self._connect() as db:
            async with db.execute(
                """
                SELECT COUNT(*) FROM telemetry_events
                WHERE event = ? AND user_hash = ? AND created_at >= ?
                """,
                (event, user_hash, since_ts),
            ) as cur:
                row = await cur.fetchone()
                return int(row[0]) if row else 0

    async def upsert_user_feedback(
        self,
        *,
        feedback_id: int | None = None,
        session_id: str | None = None,
        revision: int | None = None,
        stage: str = "unknown",
        user_hash: str | None = None,
        rating: str = "up",
        tags: list[str] | None = None,
        comment: str = "",
        context: dict[str, Any] | None = None,
    ) -> int:
        now = time.time()
        tags_json = json.dumps(tags or [])
        ctx_json = json.dumps(context or {}, default=str)
        async with self._connect() as db:
            await db.execute("PRAGMA busy_timeout=5000;")
            if feedback_id:
                cur = await db.execute(
                    """
                    UPDATE user_feedback
                    SET updated_at = ?, rating = ?, tags_json = ?, comment = ?, context_json = ?
                    WHERE id = ? AND (user_hash = ? OR user_hash IS NULL)
                    """,
                    (now, rating, tags_json, comment, ctx_json, feedback_id, user_hash),
                )
                await db.commit()
                if cur.rowcount and cur.rowcount > 0:
                    return int(feedback_id)
            cur = await db.execute(
                """
                INSERT INTO user_feedback (
                    created_at, updated_at, session_id, revision, stage, user_hash, rating, tags_json, comment, context_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (now, now, session_id, revision, stage, user_hash, rating, tags_json, comment, ctx_json),
            )
            await db.commit()
            return int(cur.lastrowid or 0)

    async def get_telemetry_summary(self, limit: int = 100) -> dict[str, Any]:
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT event, COUNT(*) as cnt FROM telemetry_events GROUP BY event ORDER BY cnt DESC"
            ) as cur:
                event_counts = {str(r["event"]): int(r["cnt"]) for r in await cur.fetchall()}

            async with db.execute(
                "SELECT COUNT(DISTINCT user_hash) FROM telemetry_events WHERE user_hash IS NOT NULL AND user_hash != ''"
            ) as cur:
                row = await cur.fetchone()
                unique_users = int(row[0]) if row else 0

            async with db.execute(
                "SELECT COUNT(DISTINCT session_id) FROM telemetry_events WHERE session_id IS NOT NULL AND session_id != ''"
            ) as cur:
                row = await cur.fetchone()
                unique_sessions = int(row[0]) if row else 0

            async with db.execute(
                """
                SELECT id, created_at, severity, event, source, session_id, stage, user_hash, payload_json
                FROM telemetry_events
                WHERE severity IN ('ERROR', 'WARNING')
                ORDER BY created_at DESC LIMIT ?
                """,
                (limit,),
            ) as cur:
                recent_errors = [
                    {**dict(r), "payload": json.loads(r["payload_json"] or "{}")}
                    for r in await cur.fetchall()
                ]
                for e in recent_errors:
                    e.pop("payload_json", None)

            async with db.execute(
                """
                SELECT id, created_at, updated_at, session_id, revision, stage, user_hash, rating, tags_json, comment, context_json
                FROM user_feedback
                ORDER BY created_at DESC LIMIT ?
                """,
                (limit,),
            ) as cur:
                feedback_rows = []
                for r in await cur.fetchall():
                    d = dict(r)
                    d["tags"] = json.loads(d.pop("tags_json") or "[]")
                    d["context"] = json.loads(d.pop("context_json") or "{}")
                    feedback_rows.append(d)

            async with db.execute(
                """
                SELECT id, created_at, severity, event, source, session_id, stage, user_hash, payload_json
                FROM telemetry_events
                ORDER BY created_at DESC LIMIT ?
                """,
                (limit,),
            ) as cur:
                recent_events = [
                    {**dict(r), "payload": json.loads(r["payload_json"] or "{}")}
                    for r in await cur.fetchall()
                ]
                for ev in recent_events:
                    ev.pop("payload_json", None)

            return {
                "unique_users": unique_users,
                "unique_sessions": unique_sessions,
                "event_counts": event_counts,
                "feedback_count": len(feedback_rows),
                "feedback": feedback_rows,
                "recent_errors": recent_errors,
                "recent_events": recent_events,
            }


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp.write_bytes(data)
    os.replace(tmp, path)


store = SessionStore()
