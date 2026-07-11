from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any

from aconex.config import ROOT_DIR


DEFAULT_DB_PATH = ROOT_DIR / "data" / "state" / "aconex.sqlite"

WORKFLOW_COLUMNS = (
    "workflow_id",
    "workflow_number",
    "workflow_number_int",
    "workflow_title",
    "review_outcome",
    "review_status",
    "step_1_completed_time",
    "step_1_due_time",
    "step_1_review_status",
    "step_1_overdue_duration_or_status",
    "step_2_completed_time",
    "step_2_due_time",
    "step_2_review_status",
    "step_2_overdue_duration_or_status",
    "is_completed",
    "last_checked_at",
    "last_changed_at",
    "source",
)

WORKFLOW_COMMENT_COLUMNS = (
    "workflow_number",
    "workflow_number_int",
    "mail_id",
    "mail_number",
    "mail_subject",
    "sent_date",
    "from_user",
    "comment_text",
    "doc_no",
    "review_step",
    "participant",
    "review_outcome",
    "review_comment",
    "source",
    "created_at",
)

DOCFLOW_SYNC_COLUMNS = (
    "workflow_id",
    "payload_hash",
    "last_synced_at",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _db_path(db_path: str | Path | None = None) -> Path:
    return Path(db_path) if db_path is not None else DEFAULT_DB_PATH


def _connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = _db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def _json_dump(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def init_db(db_path: str | Path | None = None) -> Path:
    path = _db_path(db_path)
    with _connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS workflows (
                workflow_id TEXT PRIMARY KEY,
                workflow_number TEXT,
                workflow_number_int INTEGER,
                workflow_title TEXT,
                review_outcome TEXT,
                review_status TEXT,
                step_1_completed_time TEXT,
                step_1_due_time TEXT,
                step_1_review_status TEXT,
                step_1_overdue_duration_or_status TEXT,
                step_2_completed_time TEXT,
                step_2_due_time TEXT,
                step_2_review_status TEXT,
                step_2_overdue_duration_or_status TEXT,
                is_completed INTEGER,
                last_checked_at TEXT,
                last_changed_at TEXT,
                source TEXT
            );

            CREATE TABLE IF NOT EXISTS workflow_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workflow_id TEXT,
                workflow_number TEXT,
                checked_at TEXT,
                change_summary TEXT,
                old_data_json TEXT,
                new_data_json TEXT
            );

            CREATE TABLE IF NOT EXISTS workflow_comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workflow_number TEXT,
                workflow_number_int INTEGER,
                mail_id TEXT,
                mail_number TEXT,
                mail_subject TEXT,
                sent_date TEXT,
                from_user TEXT,
                comment_text TEXT,
                doc_no TEXT,
                review_step TEXT,
                participant TEXT,
                review_outcome TEXT,
                review_comment TEXT,
                source TEXT,
                created_at TEXT,
                UNIQUE(workflow_number, mail_id)
            );

            CREATE TABLE IF NOT EXISTS update_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_time TEXT,
                command TEXT,
                checked_count INTEGER,
                changed_count INTEGER,
                failed_count INTEGER,
                notes TEXT
            );

            CREATE TABLE IF NOT EXISTS docflow_workflow_sync (
                workflow_id TEXT PRIMARY KEY,
                payload_hash TEXT NOT NULL,
                last_synced_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_workflows_open
                ON workflows(is_completed, workflow_number_int);
            CREATE INDEX IF NOT EXISTS idx_workflow_history_workflow_id
                ON workflow_history(workflow_id);
            CREATE INDEX IF NOT EXISTS idx_workflow_comments_workflow_number
                ON workflow_comments(workflow_number);
            """
        )
        _ensure_columns(
            conn,
            "workflows",
            {
                "review_outcome": "TEXT",
                "review_status": "TEXT",
                "step_1_review_status": "TEXT",
                "step_2_review_status": "TEXT",
            },
        )
        _ensure_columns(
            conn,
            "workflow_comments",
            {
                "doc_no": "TEXT",
                "review_step": "TEXT",
                "participant": "TEXT",
                "review_outcome": "TEXT",
                "review_comment": "TEXT",
            },
        )
        conn.execute(
            """
            UPDATE workflows
            SET review_status = 'Terminate',
                last_changed_at = ?
            WHERE lower(trim(coalesce(review_outcome, ''))) = 'none'
              AND coalesce(review_status, '') != 'Terminate'
            """,
            (_utc_now(),),
        )
        conn.execute(
            """
            UPDATE workflows
            SET step_1_overdue_duration_or_status = CASE
                    WHEN step_1_overdue_duration_or_status = '審批中' THEN 'pending'
                    ELSE step_1_overdue_duration_or_status
                END,
                step_2_overdue_duration_or_status = CASE
                    WHEN step_2_overdue_duration_or_status = '審批中' THEN 'pending'
                    ELSE step_2_overdue_duration_or_status
                END
            WHERE step_1_overdue_duration_or_status = '審批中'
               OR step_2_overdue_duration_or_status = '審批中'
            """
        )
    return path


def _ensure_columns(conn: sqlite3.Connection, table_name: str, columns: Mapping[str, str]) -> None:
    existing = {
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    for column, column_type in columns.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column} {column_type}")


def upsert_workflow(row: Mapping[str, Any], db_path: str | Path | None = None) -> bool:
    init_db(db_path)
    data = {column: row.get(column) for column in WORKFLOW_COLUMNS}
    if not data["workflow_id"]:
        raise ValueError("workflow_id is required")

    now = _utc_now()
    data["last_checked_at"] = data["last_checked_at"] or now

    with _connect(db_path) as conn:
        existing = conn.execute(
            "SELECT * FROM workflows WHERE workflow_id = ?",
            (data["workflow_id"],),
        ).fetchone()
        changed = existing is None or any(
            existing[column] != data[column]
            for column in WORKFLOW_COLUMNS
            if column not in {"last_checked_at", "last_changed_at", "source"}
        )
        if changed:
            data["last_changed_at"] = data["last_changed_at"] or now
        elif existing is not None:
            data["last_changed_at"] = existing["last_changed_at"]

        placeholders = ", ".join("?" for _ in WORKFLOW_COLUMNS)
        columns = ", ".join(WORKFLOW_COLUMNS)
        update_clause = ", ".join(
            f"{column} = excluded.{column}"
            for column in WORKFLOW_COLUMNS
            if column != "workflow_id"
        )
        conn.execute(
            f"""
            INSERT INTO workflows ({columns})
            VALUES ({placeholders})
            ON CONFLICT(workflow_id) DO UPDATE SET {update_clause}
            """,
            tuple(data[column] for column in WORKFLOW_COLUMNS),
        )
    return changed


def get_pending_workflows(db_path: str | Path | None = None) -> list[dict[str, Any]]:
    """Return locally stored Workflows that have not reached a completed state."""
    init_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM workflows
            WHERE is_completed IS NULL OR is_completed = 0
            ORDER BY workflow_number_int, workflow_number
            """
        ).fetchall()
    return _rows_to_dicts(rows)


def get_open_workflows(db_path: str | Path | None = None) -> list[dict[str, Any]]:
    """Backward-compatible name for pending Workflows."""
    return get_pending_workflows(db_path)


def add_workflow_history(
    workflow_id: str,
    workflow_number: str | None = None,
    checked_at: str | None = None,
    change_summary: str | None = None,
    old_data_json: Any | None = None,
    new_data_json: Any | None = None,
    db_path: str | Path | None = None,
) -> int:
    init_db(db_path)
    with _connect(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO workflow_history (
                workflow_id,
                workflow_number,
                checked_at,
                change_summary,
                old_data_json,
                new_data_json
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                workflow_id,
                workflow_number,
                checked_at or _utc_now(),
                change_summary,
                _json_dump(old_data_json) if old_data_json is not None else None,
                _json_dump(new_data_json) if new_data_json is not None else None,
            ),
        )
    return int(cursor.lastrowid)


def upsert_workflow_comment(row: Mapping[str, Any], db_path: str | Path | None = None) -> bool:
    init_db(db_path)
    data = {column: row.get(column) for column in WORKFLOW_COMMENT_COLUMNS}
    if not data["workflow_number"]:
        raise ValueError("workflow_number is required")
    if not data["mail_id"]:
        raise ValueError("mail_id is required")
    data["created_at"] = data["created_at"] or _utc_now()

    with _connect(db_path) as conn:
        existing = conn.execute(
            """
            SELECT *
            FROM workflow_comments
            WHERE workflow_number = ? AND mail_id = ?
            """,
            (data["workflow_number"], data["mail_id"]),
        ).fetchone()
        changed = existing is None or any(
            existing[column] != data[column]
            for column in WORKFLOW_COMMENT_COLUMNS
            if column != "created_at"
        )

        placeholders = ", ".join("?" for _ in WORKFLOW_COMMENT_COLUMNS)
        columns = ", ".join(WORKFLOW_COMMENT_COLUMNS)
        update_clause = ", ".join(
            f"{column} = excluded.{column}"
            for column in WORKFLOW_COMMENT_COLUMNS
            if column not in {"workflow_number", "mail_id", "created_at"}
        )
        conn.execute(
            f"""
            INSERT INTO workflow_comments ({columns})
            VALUES ({placeholders})
            ON CONFLICT(workflow_number, mail_id) DO UPDATE SET {update_clause}
            """,
            tuple(data[column] for column in WORKFLOW_COMMENT_COLUMNS),
        )
    return changed


def add_update_run(
    command: str,
    checked_count: int = 0,
    changed_count: int = 0,
    failed_count: int = 0,
    notes: str | None = None,
    run_time: str | None = None,
    db_path: str | Path | None = None,
) -> int:
    init_db(db_path)
    with _connect(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO update_runs (
                run_time,
                command,
                checked_count,
                changed_count,
                failed_count,
                notes
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                run_time or _utc_now(),
                command,
                checked_count,
                changed_count,
                failed_count,
                notes,
            ),
        )
    return int(cursor.lastrowid)


def load_workflows(db_path: str | Path | None = None) -> list[dict[str, Any]]:
    init_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM workflows ORDER BY workflow_number_int, workflow_number"
        ).fetchall()
    return _rows_to_dicts(rows)


def load_docflow_sync_state(db_path: str | Path | None = None) -> dict[str, str]:
    """Return the last successfully handled DocFlow payload hash by workflow."""
    init_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT workflow_id, payload_hash FROM docflow_workflow_sync"
        ).fetchall()
    return {str(row["workflow_id"]): str(row["payload_hash"]) for row in rows}


def upsert_docflow_sync_state(
    workflow_id: str,
    payload_hash: str,
    *,
    synced_at: str | None = None,
    db_path: str | Path | None = None,
) -> None:
    init_db(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO docflow_workflow_sync (workflow_id, payload_hash, last_synced_at)
            VALUES (?, ?, ?)
            ON CONFLICT(workflow_id) DO UPDATE SET
                payload_hash = excluded.payload_hash,
                last_synced_at = excluded.last_synced_at
            """,
            (workflow_id, payload_hash, synced_at or _utc_now()),
        )


def load_workflow_comments(db_path: str | Path | None = None) -> list[dict[str, Any]]:
    init_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM workflow_comments ORDER BY workflow_number_int, sent_date, mail_number"
        ).fetchall()
    return _rows_to_dicts(rows)


def load_update_runs(db_path: str | Path | None = None) -> list[dict[str, Any]]:
    init_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute("SELECT * FROM update_runs ORDER BY id").fetchall()
    return _rows_to_dicts(rows)
