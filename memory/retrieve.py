"""Hybrid retrieval: FastEmbed vector cosine (0.7) blended with FTS5 BM25 (0.3).

Read-only ranking over the vault from memory.vault. Every external
dependency (FastEmbed import, model load, sqlite-vec, FTS MATCH) is lazily
acquired and degrades to keyword-only, so recall never depends on model
downloads or network. Set ROOMBRAIN_NO_EMBED=1 to skip embeddings entirely.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone

from memory.vault import _open, _serialize_embedding

VECTOR_WEIGHT = 0.7
KEYWORD_WEIGHT = 0.3
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
NO_EMBED_ENV = "ROOMBRAIN_NO_EMBED"

_FTS_KEYWORDS = frozenset({"AND", "OR", "NOT", "NEAR"})
_FTS_OP_RE = re.compile(r'["\'`*^:()\[\]{}]')

_model = None


def _embeddings_disabled():
    return os.environ.get(NO_EMBED_ENV, "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _embed_query(text):
    """Embed one query string; None when disabled or unavailable.

    Process-singleton TextEmbedding, loaded lazily on the first enabled
    query only. Any failure (missing package, blocked import, model
    download error) degrades silently to None.
    """
    try:
        if _embeddings_disabled():
            return None
        global _model
        if _model is None:
            from fastembed import TextEmbedding

            _model = TextEmbedding(model_name=MODEL_NAME)
        vectors = list(_model.embed([text]))
        if not vectors:
            return None
        return [float(v) for v in vectors[0]]
    except Exception:
        return None


def _minmax(scores, invert=False):
    """Scale a {id: raw} mapping to [0, 1]; invert when lower raw is better."""
    if not scores:
        return {}
    values = list(scores.values())
    low, high = min(values), max(values)
    if high == low:
        return {key: 1.0 for key in scores}
    span = high - low
    if invert:
        return {key: (high - val) / span for key, val in scores.items()}
    return {key: (val - low) / span for key, val in scores.items()}


def _tokenize(query):
    """Split a query into FTS-safe tokens; [] when nothing searchable."""
    tokens = []
    for raw in str(query).split():
        cleaned = _FTS_OP_RE.sub(" ", raw).strip()
        cleaned = cleaned.strip("*^").strip()
        if not cleaned or cleaned.upper() in _FTS_KEYWORDS:
            continue
        tokens.append(cleaned)
    return tokens


def _vector_scores(conn, query_vector, n):
    """KNN similarity over memories_vec; {} when vec is absent or fails."""
    try:
        param = _serialize_embedding(query_vector)
        cur = conn.execute(
            "SELECT memory_id, distance FROM memories_vec"
            " WHERE embedding MATCH ? ORDER BY distance LIMIT %d" % int(n),
            (param,),
        )
        rows = cur.fetchall()
    except Exception:
        return {}
    if not rows:
        return {}
    raw = {}
    for row in rows:
        try:
            raw[int(row[0])] = 1.0 / (1.0 + float(row[1]))
        except (TypeError, ValueError):
            continue
    return _minmax(raw)


def _fts_rows(conn, match_expr, n):
    cur = conn.execute(
        "SELECT rowid, rank FROM memories_fts"
        " WHERE memories_fts MATCH ? ORDER BY rank LIMIT %d" % int(n),
        (match_expr,),
    )
    return cur.fetchall()


def _keyword_scores(conn, query, n):
    """Three-tier keyword relevance over {memory_id: score in [0, 1]}.

    Tier 1: full-string MATCH (conjunctive). Tier 2: per-token prefix OR
    MATCH so inflections (ship/ships) still rank above single-term hits.
    Tier 3: per-token LIKE coverage (each row scores by matched tokens).
    """
    tokens = _tokenize(query)
    if not tokens:
        return {}
    try:
        rows = _fts_rows(conn, str(query), n)
        if rows:
            return _minmax(
                {int(r[0]): float(r[1]) for r in rows}, invert=True
            )
    except Exception:
        pass
    try:
        quoted = ['"%s"*' % t.replace('"', "") for t in tokens]
        rows = _fts_rows(conn, " OR ".join(quoted), n)
        if rows:
            return _minmax(
                {int(r[0]): float(r[1]) for r in rows}, invert=True
            )
    except Exception:
        pass
    try:
        counts = {}
        for token in tokens:
            cur = conn.execute(
                "SELECT id FROM memories WHERE text LIKE ?",
                ("%" + token + "%",),
            )
            for (row_id,) in cur.fetchall():
                counts[int(row_id)] = counts.get(int(row_id), 0) + 1
        if not counts:
            return {}
        top = sorted(counts, key=lambda i: (-counts[i], i))[: int(n)]
        return _minmax({i: float(counts[i]) for i in top})
    except Exception:
        return {}


def _thread_link(room, thread_id):
    room = room or ""
    thread_id = thread_id or ""
    if room and thread_id:
        return "%s#%s" % (room, thread_id)
    return room or thread_id


def _enrich(row, score):
    rid, text, room, actor, thread_id, timestamp, kind, confidence = row
    date = (timestamp or "")[:10]
    link = _thread_link(room, thread_id)
    return {
        "id": rid,
        "text": text,
        "room": room,
        "actor": actor,
        "thread_id": thread_id,
        "timestamp": timestamp,
        "kind": kind,
        "confidence": confidence,
        "date": date,
        "thread_link": link,
        "score": float(score),
        "bullet": "- %s %s: %s (%s)" % (date, room, text, link),
    }


def _fetch_enriched(conn, ranked_ids, scores):
    if not ranked_ids:
        return []
    placeholders = ",".join("?" for _ in ranked_ids)
    cur = conn.execute(
        "SELECT id, text, room, actor, thread_id, timestamp, kind, confidence"
        " FROM memories WHERE id IN (%s)" % placeholders,
        list(ranked_ids),
    )
    by_id = {row[0]: row for row in cur.fetchall()}
    results = []
    for row_id in ranked_ids:
        row = by_id.get(row_id)
        if row is None:
            continue
        results.append(_enrich(row, scores.get(row_id, 0.0)))
    return results


def _keyword_only(conn, query, limit):
    scores = _keyword_scores(conn, query, max(limit * 5, 20))
    if not scores:
        return []
    ranked = sorted(scores, key=lambda i: (-scores[i], i))[:limit]
    combined = {i: KEYWORD_WEIGHT * scores[i] for i in ranked}
    return _fetch_enriched(conn, ranked, combined)


def hybrid_search(query, limit=5, db_path=None):
    """Blend vector cosine (0.7) with keyword BM25 (0.3), enriched hits.

    Returns [] for blank queries and never raises: any failure after
    opening degrades to keyword-only, then to [].
    """
    if not query or not str(query).strip():
        return []
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 5
    limit = max(1, min(limit, 50))
    try:
        conn, _ = _open(db_path, readonly=True)
    except Exception:
        return []
    try:
        try:
            query_vector = _embed_query(str(query))
        except Exception:
            query_vector = None
        vec_scores = {}
        if query_vector is not None:
            try:
                vec_scores = _vector_scores(
                    conn, query_vector, max(limit * 5, 20)
                )
            except Exception:
                vec_scores = {}
        try:
            kw_scores = _keyword_scores(
                conn, str(query), max(limit * 5, 20)
            )
        except Exception:
            kw_scores = {}
        if not vec_scores and not kw_scores:
            return []
        combined = {
            row_id: VECTOR_WEIGHT * vec_scores.get(row_id, 0.0)
            + KEYWORD_WEIGHT * kw_scores.get(row_id, 0.0)
            for row_id in set(vec_scores) | set(kw_scores)
        }
        ranked = sorted(
            combined,
            key=lambda i: (-combined[i], -kw_scores.get(i, 0.0), i),
        )[:limit]
        return _fetch_enriched(conn, ranked, combined)
    except Exception:
        try:
            return _keyword_only(conn, str(query), limit)
        except Exception:
            return []
    finally:
        try:
            conn.close()
        except Exception:
            pass


def recent_decisions(topic="", days=7, limit=20, db_path=None):
    """Latest decision-kind memories, optionally filtered by topic text.

    Topic matches text (case-insensitive ASCII LIKE) only; limit clamps
    to [1, 20].
    """
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
        conn, _ = _open(db_path, readonly=True)
    except Exception:
        return []
    try:
        sql = (
            "SELECT id, text, room, actor, thread_id, timestamp, kind,"
            " confidence FROM memories WHERE kind = 'decision'"
        )
        params: list = []
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
        return [_enrich(row, row[7]) for row in rows]
    except Exception:
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass
