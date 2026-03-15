from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from app.bot.domain import BotProfile, ClarificationRequest, ManualFormulaOverride, StoredSource


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SQLiteStorage:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS profiles (
                    telegram_id INTEGER PRIMARY KEY,
                    full_name TEXT NOT NULL,
                    group_name TEXT NOT NULL,
                    program_code TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS sources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER NOT NULL,
                    source_url TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_metadata_json TEXT,
                    status TEXT NOT NULL,
                    subject_name TEXT,
                    overall_confidence REAL,
                    progress_message TEXT,
                    last_error TEXT,
                    analysis_result_json TEXT,
                    clarification_json TEXT,
                    manual_formula_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(telegram_id, source_url)
                )
                """
            )
            _ensure_column(connection, "profiles", "program_code", "TEXT")
            _ensure_column(connection, "sources", "manual_formula_json", "TEXT")
            _ensure_column(connection, "sources", "source_metadata_json", "TEXT")


class ProfileRepository:
    def __init__(self, storage: SQLiteStorage) -> None:
        self.storage = storage

    def get(self, telegram_id: int) -> BotProfile | None:
        with self.storage._connect() as connection:
            row = connection.execute(
                "SELECT * FROM profiles WHERE telegram_id = ?",
                (telegram_id,),
            ).fetchone()
        if row is None:
            return None
        return BotProfile(
            telegram_id=row["telegram_id"],
            full_name=row["full_name"],
            group_name=row["group_name"],
            program_code=row["program_code"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def upsert(
        self,
        telegram_id: int,
        full_name: str,
        group_name: str,
        program_code: str | None = None,
    ) -> BotProfile:
        existing = self.get(telegram_id)
        now = utc_now_iso()
        created_at = existing.created_at if existing else now
        resolved_program_code = program_code if program_code is not None else (existing.program_code if existing else None)
        with self.storage._connect() as connection:
            connection.execute(
                """
                INSERT INTO profiles (telegram_id, full_name, group_name, program_code, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(telegram_id) DO UPDATE SET
                    full_name = excluded.full_name,
                    group_name = excluded.group_name,
                    program_code = excluded.program_code,
                    updated_at = excluded.updated_at
                """,
                (telegram_id, full_name, group_name, resolved_program_code, created_at, now),
            )
        return self.get(telegram_id)  # type: ignore[return-value]


class SourceRepository:
    def __init__(self, storage: SQLiteStorage) -> None:
        self.storage = storage

    def save_new(
        self,
        telegram_id: int,
        source_url: str,
        source_type: str,
        source_metadata: dict | None = None,
        subject_name: str | None = None,
        progress_message: str | None = None,
    ) -> StoredSource:
        now = utc_now_iso()
        source_metadata_json = json.dumps(source_metadata or {}, ensure_ascii=False)
        with self.storage._connect() as connection:
            connection.execute(
                """
                INSERT INTO sources (
                    telegram_id, source_url, source_type, source_metadata_json, status, subject_name,
                    overall_confidence, progress_message, last_error,
                    analysis_result_json, clarification_json, manual_formula_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, NULL, ?, NULL, NULL, NULL, NULL, ?, ?)
                ON CONFLICT(telegram_id, source_url) DO UPDATE SET
                    source_type = excluded.source_type,
                    source_metadata_json = excluded.source_metadata_json,
                    subject_name = COALESCE(excluded.subject_name, sources.subject_name),
                    status = excluded.status,
                    progress_message = excluded.progress_message,
                    updated_at = excluded.updated_at
                """,
                (
                    telegram_id,
                    source_url,
                    source_type,
                    source_metadata_json,
                    "created",
                    subject_name,
                    progress_message or "Источник сохранен.",
                    now,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT id FROM sources WHERE telegram_id = ? AND source_url = ?",
                (telegram_id, source_url),
            ).fetchone()
        return self.get(telegram_id, int(row["id"]))  # type: ignore[arg-type]

    def get(self, telegram_id: int, source_id: int) -> StoredSource | None:
        with self.storage._connect() as connection:
            row = connection.execute(
                "SELECT * FROM sources WHERE telegram_id = ? AND id = ?",
                (telegram_id, source_id),
            ).fetchone()
        return _row_to_source(row)

    def list_for_user(self, telegram_id: int) -> list[StoredSource]:
        with self.storage._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM sources WHERE telegram_id = ? ORDER BY updated_at DESC, id DESC",
                (telegram_id,),
            ).fetchall()
        return [_row_to_source(row) for row in rows if row is not None]

    def update(self, source: StoredSource) -> StoredSource:
        clarification_json = (
            json.dumps(asdict(source.clarification), ensure_ascii=False)
            if source.clarification is not None
            else None
        )
        manual_formula_json = (
            json.dumps(asdict(source.manual_formula), ensure_ascii=False)
            if source.manual_formula is not None
            else None
        )
        analysis_result_json = (
            json.dumps(source.analysis_result, ensure_ascii=False)
            if source.analysis_result is not None
            else None
        )
        source_metadata_json = json.dumps(source.source_metadata, ensure_ascii=False)
        updated_at = utc_now_iso()
        with self.storage._connect() as connection:
            connection.execute(
                """
                UPDATE sources
                SET source_metadata_json = ?, status = ?, subject_name = ?, overall_confidence = ?, progress_message = ?,
                    last_error = ?, analysis_result_json = ?, clarification_json = ?, manual_formula_json = ?, updated_at = ?
                WHERE id = ? AND telegram_id = ?
                """,
                (
                    source_metadata_json,
                    source.status,
                    source.subject_name,
                    source.overall_confidence,
                    source.progress_message,
                    source.last_error,
                    analysis_result_json,
                    clarification_json,
                    manual_formula_json,
                    updated_at,
                    source.id,
                    source.telegram_id,
                ),
            )
        refreshed = self.get(source.telegram_id, source.id)
        return refreshed if refreshed is not None else source


def _row_to_source(row: sqlite3.Row | None) -> StoredSource | None:
    if row is None:
        return None
    clarification_raw = row["clarification_json"]
    clarification = None
    if clarification_raw:
        clarification_payload = json.loads(clarification_raw)
        clarification = ClarificationRequest(**clarification_payload)
    manual_formula_raw = row["manual_formula_json"]
    manual_formula = None
    if manual_formula_raw:
        manual_formula_payload = json.loads(manual_formula_raw)
        manual_formula = ManualFormulaOverride(**manual_formula_payload)
    analysis_result = json.loads(row["analysis_result_json"]) if row["analysis_result_json"] else None
    source_metadata = json.loads(row["source_metadata_json"]) if row["source_metadata_json"] else {}
    return StoredSource(
        id=row["id"],
        telegram_id=row["telegram_id"],
        source_url=row["source_url"],
        source_type=row["source_type"],
        source_metadata=source_metadata,
        status=row["status"],
        subject_name=row["subject_name"],
        overall_confidence=row["overall_confidence"],
        progress_message=row["progress_message"],
        last_error=row["last_error"],
        analysis_result=analysis_result,
        clarification=clarification,
        manual_formula=manual_formula,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _ensure_column(connection: sqlite3.Connection, table_name: str, column_name: str, column_type: str) -> None:
    columns = {
        row["name"]
        for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    if column_name not in columns:
        connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
