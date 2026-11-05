"""Memory vault: durable SQLite store with FTS5 keyword search and optional sqlite-vec."""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone

DEFAULT_DB_PATH = os.path.join("data", "roombrain.db")
EMBEDDING_DIM = 384


def _resolve_db_path(db_path=None):
    if db_path:
        return str(db_path)
    env = os.environ.get("ROOMBRAIN_DB")
    if env:
        return env
    return DEFAULT_DB_PATH


def _try_load_vec(conn):
    try:
        import sqlite_vec  # type: ignore
    except Exception:
        return False
    try:
        try:
            conn.enable_load_extension(True)
        except Exception:
            pass
        try:
            sqlite_vec.load(conn)
        finally:
            try:
                conn.enable_load_extension(False)
            except Exception:
                pass
        return True
    except Exception:
        return False


def _ensure_schema(conn, with_vec=False):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS memories ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "text TEXT NOT NULL, "
        "room TEXT NOT NULL DEFAULT '', "
        "actor TEXT NOT NULL DEFAULT '', "
        "thread_id TEXT NOT NULL DEFAULT '', "
        "timestamp TEXT NOT NULL, "
        "kind TEXT NOT NULL DEFAULT '', "
        "confidence REAL NOT NULL DEFAULT 0.0"
        ")"
    )
    conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(text)"
    )
    if with_vec:
        try:
            conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS memories_vec "
                "USING vec0(memory_id INTEGER, embedding FLOAT[384])"
            )
        except Exception:
            pass


def _open(db_path=None):
    path = _resolve_db_path(db_path)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path)
    vec_ok = _try_load_vec(conn)
    _ensure_schema(conn, with_vec=vec_ok)
    conn.commit()
    return conn, vec_ok


def _serialize_embedding(embedding):
    try:
        vals = [float(v) for v in embedding]
    except Exception:
        raise ValueError("invalid embedding")
    return "[" + ",".join(repr(v) for v in vals) + "]"


def upsert_memory(text, room, actor, thread_id, kind, confidence,
                  embedding=None, db_path=None):
    """Insert a memory row (plain INSERT, new id) and return its integer id."""
    conn, vec_ok = _open(db_path)
    try:
        stamp = datetime.now(timezone.utc).isoformat()
        cur = conn.execute(
            "INSERT INTO memories (text, room, actor, thread_id, timestamp, kind, confidence)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (text, room, actor, thread_id, stamp, kind, float(confidence)),
        )
        row_id = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO memories_fts (rowid, text) VALUES (?, ?)",
            (row_id, text),
        )
        if embedding is not None and vec_ok:
            try:
                conn.execute(
                    "INSERT INTO memories_vec (memory_id, embedding) VALUES (?, ?)",
                    (row_id, _serialize_embedding(embedding)),
                )
            except Exception:
                pass
        conn.commit()
        return row_id
    finally:
        conn.close()


def count_memories(db_path=None):
    """Return the number of rows in memories."""
    conn, _ = _open(db_path)
    try:
        (count,) = conn.execute("SELECT COUNT(*) FROM memories").fetchone()
        return int(count)
    finally:
        conn.close()


def search_memories(query, limit=5, db_path=None):
    """Keyword search over memories; works with zero embeddings and zero vec."""
    conn, _ = _open(db_path)
    try:
        rows = []
        try:
            cur = conn.execute(
                "SELECT m.id, m.text, m.room, m.actor, m.thread_id,"
                " m.timestamp, m.kind, m.confidence"
                " FROM memories_fts JOIN memories AS m ON m.id = memories_fts.rowid"
                " WHERE memories_fts MATCH ? ORDER BY rank LIMIT %d" % int(limit),
                (query,),
            )
            rows = cur.fetchall()
        except Exception:
            rows = []
        if not rows:
            try:
                cur = conn.execute(
                    "SELECT id, text, room, actor, thread_id, timestamp, kind, confidence"
                    " FROM memories WHERE text LIKE ? ORDER BY id LIMIT %d" % int(limit),
                    ("%" + query + "%",),
                )
                rows = cur.fetchall()
            except Exception:
                rows = []
        return [
            {
                "id": r[0],
                "text": r[1],
                "room": r[2],
                "actor": r[3],
                "thread_id": r[4],
                "timestamp": r[5],
                "kind": r[6],
                "confidence": r[7],
            }
            for r in rows
        ]
    finally:
        conn.close()
