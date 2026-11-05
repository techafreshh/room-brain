"""Memory vault: durable SQLite store with FTS5 keyword search and optional sqlite-vec."""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone

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
    conn.execute(
        "CREATE TABLE IF NOT EXISTS drafts ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "draft_uid TEXT UNIQUE, "
        "kind TEXT NOT NULL DEFAULT '', "
        "topic TEXT NOT NULL DEFAULT '', "
        "body TEXT NOT NULL DEFAULT '', "
        "room TEXT NOT NULL DEFAULT '', "
        "requester TEXT NOT NULL DEFAULT '', "
        "owner TEXT NOT NULL DEFAULT '', "
        "approver TEXT NOT NULL DEFAULT '', "
        "status TEXT NOT NULL DEFAULT 'pending', "
        "created_at TEXT NOT NULL"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS room_owners ("
        "room TEXT PRIMARY KEY, "
        "owner TEXT NOT NULL, "
        "seen_at TEXT NOT NULL"
        ")"
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
                  embedding=None, db_path=None, *, timestamp=None):
    """Insert a memory row (plain INSERT, new id) and return its integer id."""
    conn, vec_ok = _open(db_path)
    try:
        stamp = timestamp or datetime.now(timezone.utc).isoformat()
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


def list_decisions(topic="", days=7, limit=20, db_path=None):
    """Latest decision-kind memories, newest first (never raises)."""
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 20
    limit = max(1, min(limit, 20))
    try:
        days = int(days)
    except (TypeError, ValueError):
        days = 7
    try:
        conn, _ = _open(db_path)
    except Exception:
        return []
    try:
        sql = (
            "SELECT id, text, room, actor, thread_id, timestamp, kind, confidence"
            " FROM memories WHERE kind = 'decision'"
        )
        params = []
        if topic and str(topic).strip():
            sql += " AND text LIKE ?"
            params.append("%" + str(topic).strip() + "%")
        if days and days > 0:
            cutoff = (
                datetime.now(timezone.utc) - timedelta(days=days)
            ).isoformat()
            sql += " AND timestamp >= ?"
            params.append(cutoff)
        sql += " ORDER BY timestamp DESC, id DESC LIMIT %d" % limit
        rows = conn.execute(sql, params).fetchall()
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
    except Exception:
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass


def hybrid_search(query, limit=5, db_path=None):
    """Ranked recall over the vault (canonical impl lives in retrieve).

    Lazy delegation avoids a vault<->retrieve import cycle while letting
    callers import hybrid_search from memory.vault, memory.retrieve, or
    memory with identical behavior.
    """
    from memory.retrieve import hybrid_search as _impl

    return _impl(query, limit, db_path=db_path)


def stage_draft(kind, topic, body, room, requester, owner="",
                db_path=None, *, created_at=None):
    """Stage one pending draft; return its id (``d<rowid>``)."""
    conn, _ = _open(db_path)
    try:
        stamp = created_at or datetime.now(timezone.utc).isoformat()
        cur = conn.execute(
            "INSERT INTO drafts (kind, topic, body, room, requester,"
            " owner, approver, status, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, '', 'pending', ?)",
            (kind or "", topic or "", body or "", room or "",
             requester or "", owner or "", stamp),
        )
        row_id = int(cur.lastrowid)
        uid = "d%d" % row_id
        try:
            conn.execute(
                "UPDATE drafts SET draft_uid = ? WHERE id = ?",
                (uid, row_id),
            )
        except Exception:
            pass
        conn.commit()
        return uid
    finally:
        conn.close()


def _draft_to_dict(row):
    return {
        "id": row[1],
        "rowid": row[0],
        "kind": row[2],
        "topic": row[3],
        "body": row[4],
        "room": row[5],
        "requester": row[6],
        "owner": row[7],
        "approver": row[8],
        "status": row[9],
        "created_at": row[10],
    }


_DRAFT_COLS = ("id", "draft_uid", "kind", "topic", "body", "room",\
               "requester", "owner", "approver", "status", "created_at")


def get_draft(draft_id, db_path=None):
    """Fetch one draft by ``d<rowid>`` id; None when unknown."""
    uid = str(draft_id or "").strip().lower()
    if not uid:
        return None
    conn, _ = _open(db_path)
    try:
        row = conn.execute(
            "SELECT " + ", ".join(_DRAFT_COLS) + " FROM drafts"
            " WHERE draft_uid = ?",
            (uid,),
        ).fetchone()
        if row is None and uid.isdigit():
            row = conn.execute(
                "SELECT " + ", ".join(_DRAFT_COLS) + " FROM drafts"
                " WHERE draft_uid = ?",
                ("d" + uid,),
            ).fetchone()
        if row is None:
            return None
        return _draft_to_dict(row)
    finally:
        conn.close()


def pending_draft_for_room(room, db_path=None):
    """Latest pending draft for a room; None when there is none."""
    conn, _ = _open(db_path)
    try:
        row = conn.execute(
            "SELECT " + ", ".join(_DRAFT_COLS) + " FROM drafts"
            " WHERE room = ? AND status = 'pending'"
            " ORDER BY id DESC LIMIT 1",
            (room or "",),
        ).fetchone()
        if row is None:
            return None
        return _draft_to_dict(row)
    finally:
        conn.close()


def mark_draft(draft_id, status, approver=None, db_path=None):
    """Update a draft's status (and approver when given)."""
    uid = str(draft_id or "").strip().lower()
    if not uid:
        return False
    conn, _ = _open(db_path)
    try:
        if approver is None:
            cur = conn.execute(
                "UPDATE drafts SET status = ? WHERE draft_uid = ?",
                (status, uid),
            )
        else:
            cur = conn.execute(
                "UPDATE drafts SET status = ?, approver = ?"
                " WHERE draft_uid = ?",
                (status, approver or "", uid),
            )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def record_room_owner(room, owner, db_path=None):
    """Persist the first human sender per room; never overwrite."""
    if not room or not owner:
        return None
    conn, _ = _open(db_path)
    try:
        stamp = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT OR IGNORE INTO room_owners (room, owner, seen_at)"
            " VALUES (?, ?, ?)",
            (room, owner, stamp),
        )
        conn.commit()
        row = conn.execute(
            "SELECT owner FROM room_owners WHERE room = ?", (room,),
        ).fetchone()
        return row[0] if row else owner
    finally:
        conn.close()


def get_room_owner(room, db_path=None):
    """Owner recorded for a room; None when no human seen yet."""
    if not room:
        return None
    conn, _ = _open(db_path)
    try:
        row = conn.execute(
            "SELECT owner FROM room_owners WHERE room = ?", (room,),
        ).fetchone()
        if row is None or not row[0]:
            return None
        return row[0]
    finally:
        conn.close()
