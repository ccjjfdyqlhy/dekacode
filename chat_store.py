import json
import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from models import Message


class ChatStore:
    def __init__(self, project_root: str):
        self.db_dir = Path(project_root) / ".dekacode"
        self.db_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.db_dir / "chat.db"
        self._session_id: Optional[str] = None
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    summary TEXT DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT,
                    tool_calls TEXT,
                    tool_call_id TEXT,
                    name TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                );
                CREATE INDEX IF NOT EXISTS idx_messages_session
                    ON messages(session_id, id);
                CREATE TABLE IF NOT EXISTS turn_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    turn INTEGER NOT NULL,
                    model TEXT,
                    input_tokens INTEGER DEFAULT 0,
                    output_tokens INTEGER DEFAULT 0,
                    cache_hit_input INTEGER DEFAULT 0,
                    cost REAL DEFAULT 0.0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                );
            """)

    def create_session(self) -> str:
        now = datetime.now().isoformat()
        session_id = datetime.now().strftime("%Y%m%d_%H%M%S%f")
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO sessions (id, created_at, updated_at) VALUES (?, ?, ?)",
                (session_id, now, now),
            )
        self._session_id = session_id
        return session_id

    def set_session(self, session_id: str) -> None:
        with sqlite3.connect(str(self.db_path)) as conn:
            cur = conn.execute("SELECT id FROM sessions WHERE id = ?", (session_id,))
            if cur.fetchone():
                self._session_id = session_id

    @property
    def session_id(self) -> Optional[str]:
        return self._session_id

    def save_messages(self, messages: list[Message]) -> None:
        if not self._session_id or not messages:
            return
        now = datetime.now().isoformat()
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (now, self._session_id),
            )
            for m in messages:
                conn.execute(
                    "INSERT INTO messages (session_id, role, content, tool_calls, tool_call_id, name, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        self._session_id,
                        m.role,
                        m.content,
                        json.dumps([tc.model_dump() for tc in m.tool_calls]) if m.tool_calls else None,
                        m.tool_call_id,
                        m.name,
                        now,
                    ),
                )

    def load_messages(self, session_id: Optional[str] = None) -> list[Message]:
        sid = session_id or self._session_id
        if not sid:
            return []
        with sqlite3.connect(str(self.db_path)) as conn:
            cur = conn.execute(
                "SELECT role, content, tool_calls, tool_call_id, name "
                "FROM messages WHERE session_id = ? ORDER BY id",
                (sid,),
            )
            results = []
            for role, content, tool_calls_json, tool_call_id, name in cur.fetchall():
                tool_calls = None
                if tool_calls_json:
                    raw = json.loads(tool_calls_json)
                    from models import Function, ToolCall
                    tool_calls = [
                        ToolCall(
                            id=tc.get("id", ""),
                            type=tc.get("type", "function"),
                            function=Function(**tc["function"]),
                        )
                        for tc in raw
                    ]
                results.append(Message(
                    role=role,
                    content=content,
                    tool_calls=tool_calls,
                    tool_call_id=tool_call_id,
                    name=name,
                ))
            return results

    def list_sessions(self, limit: int = 20) -> list[dict]:
        with sqlite3.connect(str(self.db_path)) as conn:
            cur = conn.execute(
                "SELECT s.id, s.created_at, s.updated_at, s.summary, "
                "COALESCE(m.cnt, 0), "
                "COALESCE(u.cost, 0), "
                "COALESCE(u.tok, 0) "
                "FROM sessions s "
                "LEFT JOIN (SELECT session_id, COUNT(*) AS cnt FROM messages GROUP BY session_id) m "
                "  ON s.id = m.session_id "
                "LEFT JOIN (SELECT session_id, SUM(cost) AS cost, SUM(input_tokens) AS tok "
                "           FROM turn_usage GROUP BY session_id) u "
                "  ON s.id = u.session_id "
                "ORDER BY s.updated_at DESC LIMIT ?",
                (limit,),
            )
            return [
                {
                    "id": row[0],
                    "created_at": row[1],
                    "updated_at": row[2],
                    "summary": row[3] or "",
                    "message_count": row[4],
                    "total_cost": row[5],
                    "total_input": row[6],
                }
                for row in cur.fetchall()
            ]

    def save_usage(self, turn: int, model: str, input_tokens: int, output_tokens: int, cache_hit_input: int, cost: float) -> None:
        if not self._session_id:
            return
        now = datetime.now().isoformat()
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                "INSERT INTO turn_usage (session_id, turn, model, input_tokens, output_tokens, cache_hit_input, cost, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (self._session_id, turn, model, input_tokens, output_tokens, cache_hit_input, cost, now),
            )

    def load_usage(self, session_id: Optional[str] = None) -> list[dict]:
        sid = session_id or self._session_id
        if not sid:
            return []
        with sqlite3.connect(str(self.db_path)) as conn:
            cur = conn.execute(
                "SELECT turn, model, input_tokens, output_tokens, cache_hit_input, cost "
                "FROM turn_usage WHERE session_id = ? ORDER BY turn",
                (sid,),
            )
            return [
                {"turn": r[0], "model": r[1], "input_tokens": r[2], "output_tokens": r[3],
                 "cache_hit_input": r[4], "cost": r[5]}
                for r in cur.fetchall()
            ]

    def session_cost(self, session_id: Optional[str] = None) -> float:
        sid = session_id or self._session_id
        if not sid:
            return 0.0
        with sqlite3.connect(str(self.db_path)) as conn:
            cur = conn.execute(
                "SELECT COALESCE(SUM(cost), 0) FROM turn_usage WHERE session_id = ?", (sid,)
            )
            return cur.fetchone()[0]

    def update_summary(self, summary: str) -> None:
        if not self._session_id:
            return
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                "UPDATE sessions SET summary = ? WHERE id = ?",
                (summary[:200], self._session_id),
            )
