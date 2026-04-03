"""SQLite-backed persistence for Zeph."""

from __future__ import annotations

import json
import hashlib
import hmac
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from daia.config import DB_PATH


@dataclass(slots=True)
class ScheduleRecord:
    """Represents a scheduled task."""

    task_id: str
    natural_language: str
    schedule_type: str
    schedule_value: str
    payload: str
    active: bool
    created_at: str


@dataclass(slots=True)
class UserRecord:
    """Represents a local Zeph account."""

    user_id: int
    username: str
    display_name: str
    password_hash: str
    salt: str
    created_at: str


@dataclass(slots=True)
class ConversationRecord:
    """Represents a saved local conversation."""

    conversation_id: int
    user_id: int
    title: str
    created_at: str
    updated_at: str


@dataclass(slots=True)
class ConversationMessageRecord:
    """Represents a message inside a conversation."""

    message_id: int
    conversation_id: int
    role: str
    content: str
    created_at: str


class MemoryStore:
    """Owns the SQLite schema and persistence helpers."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """Yield a configured SQLite connection."""

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _initialize(self) -> None:
        with self.connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS preferences (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS task_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task TEXT NOT NULL,
                    status TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS learned_behaviors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    app_name TEXT NOT NULL,
                    behavior_key TEXT NOT NULL,
                    behavior_value TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(app_name, behavior_key)
                );
                CREATE TABLE IF NOT EXISTS schedules (
                    task_id TEXT PRIMARY KEY,
                    natural_language TEXT NOT NULL,
                    schedule_type TEXT NOT NULL,
                    schedule_value TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS clipboard_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    salt TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tos_acceptances (
                    user_id INTEGER NOT NULL,
                    version TEXT NOT NULL,
                    accepted_at TEXT NOT NULL,
                    PRIMARY KEY(user_id, version),
                    FOREIGN KEY(user_id) REFERENCES users(id)
                );
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id)
                );
                CREATE TABLE IF NOT EXISTS conversation_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(conversation_id) REFERENCES conversations(id)
                );
                """
            )

    def set_preference(self, key: str, value: Any) -> None:
        """Store a preference value."""

        serialized = json.dumps(value)
        now = datetime.utcnow().isoformat()
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO preferences(key, value, updated_at)
                VALUES(?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (key, serialized, now),
            )

    def get_preference(self, key: str, default: Any = None) -> Any:
        """Retrieve a preference value."""

        with self.connection() as conn:
            row = conn.execute(
                "SELECT value FROM preferences WHERE key = ?",
                (key,),
            ).fetchone()
        if row is None:
            return default
        return json.loads(row["value"])

    def record_task(self, task: str, status: str, detail: str) -> None:
        """Persist an executed task."""

        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO task_history(task, status, detail, created_at)
                VALUES(?, ?, ?, ?)
                """,
                (task, status, detail, datetime.utcnow().isoformat()),
            )

    def recent_tasks(self, limit: int = 10) -> list[sqlite3.Row]:
        """Return recent task entries."""

        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT task, status, detail, created_at
                FROM task_history
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return list(rows)

    def set_behavior(self, app_name: str, key: str, value: Any) -> None:
        """Store a learned behavior value for an app."""

        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO learned_behaviors(app_name, behavior_key, behavior_value, updated_at)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(app_name, behavior_key) DO UPDATE SET
                    behavior_value = excluded.behavior_value,
                    updated_at = excluded.updated_at
                """,
                (
                    app_name,
                    key,
                    json.dumps(value),
                    datetime.utcnow().isoformat(),
                ),
            )

    def get_behaviors(self, app_name: str) -> dict[str, Any]:
        """Load all learned behaviors for an app."""

        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT behavior_key, behavior_value
                FROM learned_behaviors
                WHERE app_name = ?
                """,
                (app_name,),
            ).fetchall()
        return {row["behavior_key"]: json.loads(row["behavior_value"]) for row in rows}

    def add_clipboard_entry(self, content: str, limit: int = 20) -> None:
        """Append a clipboard history entry and trim the table."""

        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO clipboard_history(content, created_at)
                VALUES(?, ?)
                """,
                (content, datetime.utcnow().isoformat()),
            )
            conn.execute(
                """
                DELETE FROM clipboard_history
                WHERE id NOT IN (
                    SELECT id FROM clipboard_history
                    ORDER BY id DESC
                    LIMIT ?
                )
                """,
                (limit,),
            )

    def clipboard_history(self, limit: int = 20) -> list[sqlite3.Row]:
        """Return recent clipboard entries."""

        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT id, content, created_at
                FROM clipboard_history
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return list(rows)

    def save_schedule(
        self,
        task_id: str,
        natural_language: str,
        schedule_type: str,
        schedule_value: str,
        payload: dict[str, Any],
        active: bool = True,
    ) -> None:
        """Persist a scheduled task."""

        with self.connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO schedules(
                    task_id, natural_language, schedule_type, schedule_value, payload, active, created_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    natural_language,
                    schedule_type,
                    schedule_value,
                    json.dumps(payload),
                    1 if active else 0,
                    datetime.utcnow().isoformat(),
                ),
            )

    def list_schedules(self) -> list[ScheduleRecord]:
        """Return all stored schedules."""

        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT task_id, natural_language, schedule_type, schedule_value, payload, active, created_at
                FROM schedules
                ORDER BY created_at DESC
                """
            ).fetchall()
        return [
            ScheduleRecord(
                task_id=row["task_id"],
                natural_language=row["natural_language"],
                schedule_type=row["schedule_type"],
                schedule_value=row["schedule_value"],
                payload=row["payload"],
                active=bool(row["active"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def set_schedule_active(self, task_id: str, active: bool) -> None:
        """Pause or resume a schedule."""

        with self.connection() as conn:
            conn.execute(
                "UPDATE schedules SET active = ? WHERE task_id = ?",
                (1 if active else 0, task_id),
            )

    def delete_schedule(self, task_id: str) -> None:
        """Delete a schedule."""

        with self.connection() as conn:
            conn.execute("DELETE FROM schedules WHERE task_id = ?", (task_id,))

    def summarize_recent_activity(self, limit: int = 5) -> str:
        """Return a friendly text summary of recent activity."""

        rows = self.recent_tasks(limit=limit)
        if not rows:
            return "No recent activity recorded yet."
        lines = [
            f"{row['created_at'][:19]} - {row['status'].upper()}: {row['task']}"
            for row in rows
        ]
        return "\n".join(lines)

    @staticmethod
    def _hash_password(password: str, salt: str) -> str:
        """Create a password hash using PBKDF2."""

        return hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt),
            120_000,
        ).hex()

    def create_user(self, username: str, display_name: str, password: str) -> UserRecord:
        """Create a local user account."""

        normalized_username = username.strip().lower()
        if not normalized_username:
            raise ValueError("Username cannot be empty.")
        if len(password) < 8:
            raise ValueError("Password must be at least 8 characters.")
        salt = os.urandom(16).hex()
        password_hash = self._hash_password(password, salt)
        created_at = datetime.utcnow().isoformat()
        with self.connection() as conn:
            try:
                cursor = conn.execute(
                    """
                    INSERT INTO users(username, display_name, password_hash, salt, created_at)
                    VALUES(?, ?, ?, ?, ?)
                    """,
                    (normalized_username, display_name.strip() or username.strip(), password_hash, salt, created_at),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("That username is already in use.") from exc
        return UserRecord(
            user_id=int(cursor.lastrowid),
            username=normalized_username,
            display_name=display_name.strip() or username.strip(),
            password_hash=password_hash,
            salt=salt,
            created_at=created_at,
        )

    def get_user_by_username(self, username: str) -> UserRecord | None:
        """Load a user by username."""

        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT id, username, display_name, password_hash, salt, created_at
                FROM users
                WHERE username = ?
                """,
                (username.strip().lower(),),
            ).fetchone()
        if row is None:
            return None
        return UserRecord(
            user_id=int(row["id"]),
            username=str(row["username"]),
            display_name=str(row["display_name"]),
            password_hash=str(row["password_hash"]),
            salt=str(row["salt"]),
            created_at=str(row["created_at"]),
        )

    def authenticate_user(self, username: str, password: str) -> UserRecord | None:
        """Validate a username and password."""

        user = self.get_user_by_username(username)
        if user is None:
            return None
        candidate = self._hash_password(password, user.salt)
        if not hmac.compare_digest(candidate, user.password_hash):
            return None
        return user

    def has_tos_acceptance(self, user_id: int, version: str) -> bool:
        """Return whether the user has accepted a specific TOS version."""

        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM tos_acceptances
                WHERE user_id = ? AND version = ?
                """,
                (user_id, version),
            ).fetchone()
        return row is not None

    def accept_tos(self, user_id: int, version: str) -> None:
        """Persist TOS acceptance for a user."""

        with self.connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO tos_acceptances(user_id, version, accepted_at)
                VALUES(?, ?, ?)
                """,
                (user_id, version, datetime.utcnow().isoformat()),
            )

    def create_conversation(self, user_id: int, title: str = "New chat") -> ConversationRecord:
        """Create a new conversation for a user."""

        now = datetime.utcnow().isoformat()
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO conversations(user_id, title, created_at, updated_at)
                VALUES(?, ?, ?, ?)
                """,
                (user_id, title.strip() or "New chat", now, now),
            )
        return ConversationRecord(
            conversation_id=int(cursor.lastrowid),
            user_id=user_id,
            title=title.strip() or "New chat",
            created_at=now,
            updated_at=now,
        )

    def list_conversations(self, user_id: int, limit: int = 100) -> list[ConversationRecord]:
        """Return saved conversations for a user."""

        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT id, user_id, title, created_at, updated_at
                FROM conversations
                WHERE user_id = ?
                ORDER BY updated_at DESC, id DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return [
            ConversationRecord(
                conversation_id=int(row["id"]),
                user_id=int(row["user_id"]),
                title=str(row["title"]),
                created_at=str(row["created_at"]),
                updated_at=str(row["updated_at"]),
            )
            for row in rows
        ]

    def update_conversation_title(self, conversation_id: int, title: str) -> None:
        """Rename a conversation and bump its updated timestamp."""

        with self.connection() as conn:
            conn.execute(
                """
                UPDATE conversations
                SET title = ?, updated_at = ?
                WHERE id = ?
                """,
                (title.strip() or "New chat", datetime.utcnow().isoformat(), conversation_id),
            )

    def delete_conversation(self, conversation_id: int) -> None:
        """Delete a conversation and all messages."""

        with self.connection() as conn:
            conn.execute("DELETE FROM conversation_messages WHERE conversation_id = ?", (conversation_id,))
            conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))

    def add_conversation_message(self, conversation_id: int, role: str, content: str) -> ConversationMessageRecord:
        """Append a message to a conversation."""

        now = datetime.utcnow().isoformat()
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO conversation_messages(conversation_id, role, content, created_at)
                VALUES(?, ?, ?, ?)
                """,
                (conversation_id, role, content, now),
            )
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now, conversation_id),
            )
        return ConversationMessageRecord(
            message_id=int(cursor.lastrowid),
            conversation_id=conversation_id,
            role=role,
            content=content,
            created_at=now,
        )

    def list_conversation_messages(self, conversation_id: int) -> list[ConversationMessageRecord]:
        """Return messages for a conversation in chronological order."""

        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT id, conversation_id, role, content, created_at
                FROM conversation_messages
                WHERE conversation_id = ?
                ORDER BY id ASC
                """,
                (conversation_id,),
            ).fetchall()
        return [
            ConversationMessageRecord(
                message_id=int(row["id"]),
                conversation_id=int(row["conversation_id"]),
                role=str(row["role"]),
                content=str(row["content"]),
                created_at=str(row["created_at"]),
            )
            for row in rows
        ]
