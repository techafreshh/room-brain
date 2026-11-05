"""Transport-agnostic room commands: remember / recall / decisions.

Pure functions over the vault that return reply text; the protocol loop
stays a thin adapter that posts the reply once. Retrieval is keyword-only
by default (ROOMBRAIN_NO_EMBED=1 unless the operator opts out) so a cold
FastEmbed model download never stalls the live reply path.
"""

import os

os.environ.setdefault("ROOMBRAIN_NO_EMBED", "1")


def _link(room, thread_id):
    room = room or ""
    thread_id = thread_id or ""
    if room and thread_id:
        return "%s#%s" % (room, thread_id)
    return room or thread_id


def _bullet(text, room, thread_id, timestamp):
    date = (timestamp or "")[:10]
    return "- %s %s: %s (%s)" % (date, room or "", text, _link(room, thread_id))


def _row_to_hit(row):
    text = row.get("text", "")
    room = row.get("room", "") or ""
    thread_id = row.get("thread_id", "") or ""
    return {
        "text": text,
        "room": room,
        "thread_id": thread_id,
        "date": (row.get("timestamp") or "")[:10],
        "bullet": _bullet(text, room, thread_id, row.get("timestamp") or ""),
    }


def _search_recall(query, limit=5, db_path=None):
    """Keyword-first recall hits with {text, room, thread_id, bullet}."""
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 5
    limit = max(1, min(limit, 5))
    try:
        from memory.retrieve import hybrid_search

        try:
            hits = hybrid_search(query, limit=limit, db_path=db_path)
        except Exception:
            hits = None
        if hits:
            out = []
            for hit in hits[:limit]:
                if isinstance(hit, dict) and hit.get("bullet"):
                    out.append(hit)
                elif isinstance(hit, dict):
                    out.append(_row_to_hit(hit))
            if out:
                return out
        if hits is not None:
            return []
    except ImportError:
        pass
    try:
        from memory.vault import search_memories

        rows = search_memories(query, limit=limit, db_path=db_path)
    except Exception:
        return []
    return [_row_to_hit(row) for row in (rows or [])[:limit]]


def _search_decisions(topic="", db_path=None, limit=10):
    """Decision hits for the last 7 days with {text, bullet}."""
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 10
    limit = max(1, min(limit, 10))
    want = max(limit, 20)
    if want > 20:
        want = 20
    try:
        from memory.retrieve import recent_decisions

        try:
            hits = recent_decisions(
                topic or "", days=7, limit=want, db_path=db_path
            )
        except Exception:
            hits = None
        if hits:
            out = []
            for hit in hits[:limit]:
                if isinstance(hit, dict) and hit.get("bullet"):
                    out.append(hit)
                elif isinstance(hit, dict):
                    out.append(_row_to_hit(hit))
            if out:
                return out
        if hits is not None:
            return []
    except ImportError:
        pass
    try:
        from memory.vault import list_decisions

        rows = list_decisions(topic or "", days=7, limit=want, db_path=db_path)
    except Exception:
        return []
    return [_row_to_hit(row) for row in (rows or [])[:limit]]


def handle_remember(fact, *, room="", actor="", thread_id="", db_path=None):
    """Store one explicit decision; reply confirms with the vault count."""
    text = (fact or "").strip() if isinstance(fact, str) else str(fact).strip()
    if not text:
        return "usage: !remember <fact>"
    from memory.vault import count_memories, upsert_memory

    upsert_memory(text, room or "", actor or "", thread_id or "",
                  "decision", 1.0, db_path=db_path)
    try:
        total = count_memories(db_path=db_path)
    except Exception:
        total = 0
    return 'remembered "%s" (vault now holds %d)' % (text, total)


def handle_recall(query, *, room="", actor="", thread_id="",
                  db_path=None, limit=5):
    """Answer a recall query with dated bullets carrying thread links."""
    text = query.strip() if isinstance(query, str) else str(query or "").strip()
    if not text:
        return "usage: !recall <query>"
    hits = _search_recall(text, limit=limit, db_path=db_path)
    if not hits:
        return 'no memories match "%s"' % text
    lines = []
    for hit in hits[:5]:
        bullet = hit.get("bullet", "") if isinstance(hit, dict) else ""
        if bullet:
            lines.append(bullet)
    if not lines:
        return 'no memories match "%s"' % text
    return 'recall: %d hit(s) for "%s":\n%s' % (len(lines), text, "\n".join(lines))


def handle_decisions(topic="", *, room="", actor="", thread_id="",
                     db_path=None, limit=10):
    """List the last 7 days of decisions as dated bullets."""
    query = topic.strip() if isinstance(topic, str) else str(topic or "").strip()
    hits = _search_decisions(query, db_path=db_path, limit=limit)
    if not hits:
        return "no decisions in the last 7 days"
    lines = []
    for hit in hits[:10]:
        bullet = hit.get("bullet", "") if isinstance(hit, dict) else ""
        if bullet:
            lines.append(bullet)
    if not lines:
        return "no decisions in the last 7 days"
    return "decisions (last 7 days):\n%s" % "\n".join(lines)


def dispatch_command(name, args, ctx=None):
    """Route one parsed command to its handler; None for unknown names."""
    if name not in ("remember", "recall", "decisions"):
        return None
    ctx = ctx or {}
    room = ctx.get("room", "") or ""
    actor = ctx.get("actor", ctx.get("sender", "")) or ""
    thread_id = ctx.get("thread_id", ctx.get("thread", "")) or ""
    db_path = ctx.get("db_path")
    words = list(args or [])
    if name == "remember":
        fact = " ".join(str(w) for w in words).strip()
        return handle_remember(fact, room=room, actor=actor,
                               thread_id=thread_id, db_path=db_path)
    if name == "recall":
        query = " ".join(str(w) for w in words).strip()
        return handle_recall(query, room=room, actor=actor,
                             thread_id=thread_id, db_path=db_path)
    topic = " ".join(str(w) for w in words).strip()
    return handle_decisions(topic, room=room, actor=actor,
                            thread_id=thread_id, db_path=db_path)
