import json
import os
import sqlite3
import time

from code_graph.symbol import CallGraph, Symbol


class GraphCache:
    def __init__(self, project_root: str):
        self.project_root = os.path.abspath(project_root)
        db_dir = os.path.join(self.project_root, ".dekacode")
        os.makedirs(db_dir, exist_ok=True)
        self.db_path = os.path.join(db_dir, "codegraph_cache.db")
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS file_mtimes (
                    file_path TEXT PRIMARY KEY,
                    mtime REAL,
                    size INTEGER
                );
                CREATE TABLE IF NOT EXISTS symbols (
                    name TEXT PRIMARY KEY,
                    kind TEXT,
                    file_path TEXT,
                    line INTEGER,
                    signature TEXT,
                    calls TEXT,
                    called_by TEXT
                );
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );
            """)

    def is_fresh(self) -> bool:
        py_files = self._find_py_files()
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute("SELECT file_path, mtime, size FROM file_mtimes")
            cached = {row[0]: (row[1], row[2]) for row in cur.fetchall()}

        for fpath in py_files:
            stat = os.stat(fpath)
            key = os.path.relpath(fpath, self.project_root)
            cached_mtime_size = cached.get(key)
            if cached_mtime_size is None:
                return False
            if abs(stat.st_mtime - cached_mtime_size[0]) > 0.1 or stat.st_size != cached_mtime_size[1]:
                return False
        return len(cached) == len(py_files)

    def save(self, graph: CallGraph) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM file_mtimes")
            conn.execute("DELETE FROM symbols")
            conn.execute("DELETE FROM meta")

            py_files = self._find_py_files()
            for fpath in py_files:
                stat = os.stat(fpath)
                key = os.path.relpath(fpath, self.project_root)
                conn.execute(
                    "INSERT INTO file_mtimes (file_path, mtime, size) VALUES (?, ?, ?)",
                    (key, stat.st_mtime, stat.st_size),
                )

            for name, sym in graph.symbols.items():
                conn.execute(
                    "INSERT INTO symbols (name, kind, file_path, line, signature, calls, called_by) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        name,
                        sym.kind,
                        sym.file_path,
                        sym.line,
                        sym.signature,
                        json.dumps(sym.calls),
                        json.dumps(sym.called_by),
                    ),
                )

            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                ("updated_at", str(time.time())),
            )

    def load(self) -> CallGraph | None:
        if not os.path.isfile(self.db_path):
            return None
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute("SELECT name, kind, file_path, line, signature, calls, called_by FROM symbols")
            rows = cur.fetchall()
            if not rows:
                return None
            graph = CallGraph()
            for name, kind, fpath, line, sig, calls_json, called_by_json in rows:
                graph.symbols[name] = Symbol(
                    name=name,
                    kind=kind,
                    file_path=fpath,
                    line=line,
                    signature=sig,
                    calls=json.loads(calls_json),
                    called_by=json.loads(called_by_json),
                )
                graph.files.add(fpath)

            cur = conn.execute("SELECT file_path FROM file_mtimes")
            for row in cur.fetchall():
                graph.files.add(row[0])

        return graph

    def _find_py_files(self) -> list[str]:
        results = []
        for root, dirs, files in os.walk(self.project_root):
            dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", ".dekacode")]
            for f in files:
                if f.endswith(".py"):
                    results.append(os.path.join(root, f))
        return results

    def mark_dirty(self, file_path: str) -> None:
        rel = os.path.relpath(file_path, self.project_root)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM file_mtimes WHERE file_path = ?", (rel,))
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                ("dirty_file", rel),
            )

    def clear(self) -> None:
        if os.path.isfile(self.db_path):
            os.remove(self.db_path)
