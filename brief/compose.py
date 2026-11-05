"""Daily brief composer: yesterday captures plus activity markdown.

Transport-agnostic: reads the vault only. No agent/ imports, no LLM,
no network. Delivery lives in roombrain/agent/ops.py and roombrain/cli.py.
"""

from datetime import datetime, timedelta, timezone


def _cutoff_iso(now=None):
    """ISO timestamp for 00:00 UTC yesterday (the "yesterday" window start)."""
    ref = now or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    midnight = ref.replace(hour=0, minute=0, second=0, microsecond=0)
    return (midnight - timedelta(days=1)).isoformat()


def _bullet(text, room, thread_id, timestamp):
    date = (timestamp or "")[:10]
    room = room or ""
    thread_id = thread_id or ""
    if room and thread_id:
        link = "%s#%s" % (room, thread_id)
    else:
        link = room or thread_id
    return "- %s %s: %s (%s)" % (date, room, text, link)


def compose_brief(room="", db_path=None, now=None):
    """Build the morning-brief markdown for a delivery-target room.

    Room-unfiltered: room selects only the title label and delivery
    target, never which decisions appear. Always carries a Decisions
    section; the empty case renders the literal "No decisions yesterday.".
    """
    cutoff = _cutoff_iso(now)
    try:
        from memory.vault import list_decisions

        rows = list_decisions("", days=7, limit=20, db_path=db_path)
    except Exception:
        rows = []
    recent = [
        row for row in (rows or [])
        if isinstance(row, dict) and (row.get("timestamp") or "") >= cutoff
    ]
    bullets = [
        _bullet(
            row.get("text", ""),
            row.get("room", "") or "",
            row.get("thread_id", "") or "",
            row.get("timestamp") or "",
        )
        for row in recent[:10]
    ]
    try:
        from memory.vault import count_memories

        total = count_memories(db_path=db_path)
    except Exception:
        total = 0
    lines = [
        "# Morning Brief for %s" % (room or "all rooms"),
        "",
        "## Decisions (%d)" % len(bullets),
    ]
    if bullets:
        lines.extend(bullets)
    else:
        lines.append("No decisions yesterday.")
    lines += ["", "Activity: %d memories in vault." % total]
    return "\n".join(lines) + "\n"
