"""Approval gate core: draft / approve / reject (transport-agnostic)."""

from __future__ import annotations

import os
from datetime import datetime, timezone

EXPIRY_SECONDS = 24 * 3600
_VALID_KINDS = ("email", "linear")


def _db_path(ctx):
    if isinstance(ctx, dict) and ctx.get("db_path"):
        return ctx.get("db_path")
    return None


def _sent_dir():
    override = (os.environ.get("ROOMBRAIN_SENT_DIR") or "").strip()
    return override or "sent"


def is_agent_sender(sender, own_id=None):
    empty = not str(sender or "").strip()
    if empty:
        return True
    text = str(sender).strip()
    if own_id and text == str(own_id):
        return True
    lowered = text.lower()
    return ("agent" in lowered) or ("bot" in lowered)


def ensure_owner(room, sender, db_path=None, ctx=None):
    from memory.vault import get_room_owner, record_room_owner

    if ctx is not None and db_path is None:
        db_path = _db_path(ctx)
    if not room:
        return None
    if is_agent_sender(sender):
        try:
            return get_room_owner(room, db_path=db_path)
        except Exception:
            return None
    name = str(sender or "").strip()
    if not name:
        try:
            return get_room_owner(room, db_path=db_path)
        except Exception:
            return None
    try:
        return record_room_owner(room, name, db_path=db_path)
    except Exception:
        return name


def _context_lines(topic, db_path=None):
    try:
        from memory.vault import search_memories

        rows = search_memories(str(topic or ""), limit=3, db_path=db_path)
    except Exception:
        return []
    lines = []
    for row in (rows or [])[:3]:
        try:
            text = str(row.get("text", "") or "").strip()
        except Exception:
            continue
        if text:
            lines.append(text)
    return lines


def _compose_body(kind, topic, db_path=None):
    lines = _context_lines(topic, db_path=db_path)
    if kind == "email":
        head = "Subject: " + topic
    else:
        head = "Title: " + topic
    if lines:
        context = chr(10).join("- " + line for line in lines)
    else:
        context = "- (no vault context)"
    return head + chr(10) + chr(10) + "Context from vault:" + chr(10) + context


def _draft_age_seconds(draft):
    try:
        stamp = str(draft.get("created_at", "") or "")
        if stamp.endswith("Z"):
            stamp = stamp[:-1] + "+00:00"
        created = datetime.fromisoformat(stamp)
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - created
        return delta.total_seconds()
    except Exception:
        return 0.0


def _is_expired(draft):
    return _draft_age_seconds(draft) > EXPIRY_SECONDS


def _archive_sent(draft, approver):
    directory = _sent_dir()
    os.makedirs(directory, exist_ok=True)
    draft_id = str(draft.get("id", "") or "")
    stamp = datetime.now(timezone.utc).isoformat()
    lines = [
        "# " + draft_id + " " + str(draft.get("kind", "")) + ": "
        + str(draft.get("topic", "")),
        "",
        "Room: " + str(draft.get("room", "")),
        "Requester: " + str(draft.get("requester", "")),
        "Owner: " + str(draft.get("owner", "")),
        "Approver: " + str(approver or ""),
        "Approved: " + stamp,
        "Status: approval recorded; send skipped",
        "",
        str(draft.get("body", "")),
        "",
    ]
    path = os.path.join(directory, draft_id + ".md")
    try:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(chr(10).join(lines))
    except Exception:
        pass
    return path


def handle_draft(kind, topic, ctx=None):
    from memory.vault import stage_draft

    ctx = ctx or {}
    kind = str(kind or "").strip().lower()
    topic = str(topic or "").strip() if topic is not None else ""
    if kind not in _VALID_KINDS:
        return "usage: !draft <email|linear> <topic>"
    if not topic:
        return "usage: !draft <email|linear> <topic>"
    room = str(ctx.get("room", "") or "")
    sender = str(ctx.get("sender", ctx.get("requester", "")) or "")
    db_path = _db_path(ctx)
    body = _compose_body(kind, topic, db_path=db_path)
    try:
        owner = ensure_owner(room, sender, db_path=db_path)
    except Exception:
        owner = None
    try:
        draft_id = stage_draft(
            kind, topic, body, room, sender, owner or "", db_path=db_path
        )
    except Exception:
        return "draft failed; try again"
    return (
        "draft "
        + draft_id
        + " staged ("
        + kind
        + "): "
        + topic
        + " -- reply !approve "
        + draft_id
        + " or !reject "
        + draft_id
    )


def _resolve_draft(arg, room, db_path):
    from memory.vault import get_draft, pending_draft_for_room

    wanted = str(arg or "").strip().lower()
    if wanted:
        return get_draft(wanted, db_path=db_path)
    return pending_draft_for_room(room, db_path=db_path)


def _authorized(sender, draft, room, ctx, db_path):
    from memory.vault import get_room_owner

    name = str(sender or "").strip()
    if not name:
        return False
    own_id = None
    if isinstance(ctx, dict):
        own_id = ctx.get("agent_id", ctx.get("own_id"))
    if is_agent_sender(name, own_id):
        return False
    try:
        owner = get_room_owner(room, db_path=db_path)
    except Exception:
        owner = None
    candidates = set()
    for value in (owner or "", draft.get("requester", "") or "",
                  draft.get("owner", "") or ""):
        if value:
            candidates.add(value)
    if not candidates:
        return True
    return name in candidates


def handle_approve(arg, ctx=None):
    from memory.vault import mark_draft

    ctx = ctx or {}
    room = str(ctx.get("room", "") or "")
    sender = str(ctx.get("sender", ctx.get("requester", "")) or "")
    db_path = _db_path(ctx)
    try:
        ensure_owner(room, sender, db_path=db_path)
    except Exception:
        pass
    try:
        draft = _resolve_draft(arg, room, db_path)
    except Exception:
        draft = None
    if draft is None:
        return "no pending draft"
    if _is_expired(draft):
        try:
            mark_draft(draft.get("id"), "expired", db_path=db_path)
        except Exception:
            pass
        return "draft " + str(draft.get("id", "")) + " expired"
    if not _authorized(sender, draft, room, ctx, db_path):
        return "not authorized: only the room owner can approve"
    try:
        mark_draft(draft.get("id"), "approved", approver=sender,
                   db_path=db_path)
    except Exception:
        pass
    sent_ok = False
    try:
        if draft.get("kind") == "linear":
            from actions.linear_action import create_issue

            sent_ok = bool(create_issue(draft))
        else:
            from actions.gmail_action import send_draft

            sent_ok = bool(send_draft(draft))
    except Exception:
        sent_ok = False
    try:
        _archive_sent(draft, sender)
    except Exception:
        pass
    if sent_ok:
        return "sent " + str(draft.get("kind", "")) + " " + str(draft.get("id", ""))
    return (
        "approval recorded; send skipped (draft "
        + str(draft.get("id", ""))
        + " archived to sent/"
        + str(draft.get("id", ""))
        + ".md)"
    )


def handle_reject(arg, ctx=None):
    from memory.vault import mark_draft

    ctx = ctx or {}
    room = str(ctx.get("room", "") or "")
    db_path = _db_path(ctx)
    try:
        draft = _resolve_draft(arg, room, db_path)
    except Exception:
        draft = None
    if draft is None:
        return "no pending draft"
    if _is_expired(draft):
        try:
            mark_draft(draft.get("id"), "expired", db_path=db_path)
        except Exception:
            pass
        return "draft " + str(draft.get("id", "")) + " expired"
    try:
        mark_draft(draft.get("id"), "discarded", db_path=db_path)
    except Exception:
        pass
    return "draft " + str(draft.get("id", "")) + " discarded"


def dispatch_gate(name, args, ctx=None):
    ctx = ctx or {}
    if name not in ("draft", "approve", "reject"):
        return None
    words = [str(w) for w in (args or [])]
    if name == "draft":
        kind = words[0] if words else ""
        topic = " ".join(words[1:]).strip() if len(words) > 1 else ""
        return handle_draft(kind, topic, ctx)
    target = words[0] if words else ""
    if name == "approve":
        return handle_approve(target, ctx)
    return handle_reject(target, ctx)
