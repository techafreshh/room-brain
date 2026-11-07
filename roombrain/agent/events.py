"""WebSocket frame models and tolerant field readers (pydantic v2).

Frames arrive as JSON text. The envelope-vs-payload shape is wire-unconfirmed,
so every field is read top-level first, then one level inside the first nested
dict found under payload/data/state. Unknown fields are ignored so the agent
stays forward compatible with new frame members.
"""

import json

from pydantic import BaseModel, ConfigDict

TAKEOVER_CODE = "taken_over"
EXIT_TAKEOVER = 3

_NESTED_KEYS = ("payload", "data", "state")


class ConnectionState(BaseModel):
    """Snapshot carried by the first `connection_state` frame."""

    model_config = ConfigDict(extra="ignore")

    connection_id: str = ""
    agent_id: str = ""
    generation: int = 0
    cursor: int = 0
    rooms: list = []


class Evicted(BaseModel):
    """Server-directed eviction; `taken_over` is terminal (exit 3)."""

    model_config = ConfigDict(extra="ignore")

    code: str = ""


def parse_frame(raw):
    """Decode one raw frame into a dict; garbage yields {}."""
    try:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        if not isinstance(raw, str):
            return {}
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def frame_type(frame):
    """Frame type of a frame, "" when absent or not a string.

    Wire-confirmed 2026-11-06 against switch-core v0.31.0: frames arrive as
    `{"event": name, "data": {...}, "id": seq}` — `event` is the type
    carrier. The documented flat `{"type": name}` shape stays first for
    forward/backward compatibility.
    """
    value = frame_get(frame, "type", "event")
    return value if isinstance(value, str) else ""


def frame_get(frame, *names):
    """Case-sensitive lookup: top-level first, then one level inside the
    first nested dict found under payload/data/state, then that dict's own
    `payload` (v0.31.0 wraps message fields at data.payload.*). None when
    absent."""
    if not isinstance(frame, dict):
        return None
    for name in names:
        if name in frame:
            return frame[name]
    nested = None
    for key in _NESTED_KEYS:
        value = frame.get(key)
        if isinstance(value, dict):
            nested = value
            break
    if nested is None:
        return None
    for name in names:
        if name in nested:
            return nested[name]
    inner = nested.get("payload")
    if isinstance(inner, dict):
        for name in names:
            if name in inner:
                return inner[name]
    return None


def _as_int(value):
    """Strict int coercion (bools rejected); None when not an int."""
    if isinstance(value, bool):
        return None
    return value if isinstance(value, int) else None


def _as_str(value):
    return value if isinstance(value, str) else ""


def parse_connection_state(frame):
    """Build a ConnectionState from a frame; None unless it is a
    `connection_state` frame carrying int generation and cursor."""
    if frame_type(frame) != "connection_state":
        return None
    generation = _as_int(frame_get(frame, "generation"))
    cursor = _as_int(frame_get(frame, "cursor", "sequence", "seq"))
    if generation is None or cursor is None:
        return None
    rooms = frame_get(frame, "rooms")
    if isinstance(rooms, str):
        rooms = [rooms] if rooms else []
    if not isinstance(rooms, list):
        rooms = []
    try:
        return ConnectionState(
            connection_id=_as_str(frame_get(frame, "connection_id")),
            agent_id=_as_str(frame_get(frame, "agent_id")),
            generation=generation,
            cursor=cursor,
            rooms=rooms,
        )
    except Exception:
        return None


def parse_evicted(frame):
    """Build an Evicted from a frame; None unless type is `evicted`."""
    if frame_type(frame) != "evicted":
        return None
    code = frame_get(frame, "code")
    return Evicted(code=code if isinstance(code, str) else "")


def is_taken_over(frame):
    """True when the frame evicts this connection with code `taken_over`."""
    if frame_type(frame) != "evicted":
        return False
    return frame_get(frame, "code") == TAKEOVER_CODE


def advance_cursor(cursor, frame):
    """Monotonic cursor: max() over int sequence/seq/cursor/id, never back.

    `id` is v0.31.0's top-level per-frame sequence (echoed as data.sequence);
    reconnects pass it back as start_from.
    """
    for name in ("sequence", "seq", "cursor", "id"):
        value = _as_int(frame_get(frame, name))
        if value is not None and value > cursor:
            cursor = value
    return cursor


def message_body(frame):
    """Body of an addressed `message` frame, else None (never dispatch)."""
    if frame_type(frame) != "message":
        return None
    if not frame_get(frame, "addressed", "addressed_to_me"):
        return None
    body = frame_get(frame, "body", "text", "content")
    if body is None:
        return None
    return body if isinstance(body, str) else str(body)


def parse_command(body):
    """Split a `!`-prefixed body into (name, args); None otherwise.

    A leading `@mention` (how chat surfaces address an agent) is tolerated
    and skipped, so both `!remember x` and `@roombrain !remember x` parse.
    """
    if not isinstance(body, str):
        return None
    stripped = body.strip()
    if stripped.startswith("@"):
        _mention, _, rest = stripped.partition(" ")
        stripped = rest.strip()
    if not stripped.startswith("!"):
        return None
    rest = stripped[1:]
    if not rest or rest[0].isspace():
        return None
    parts = rest.split()
    if not parts or not parts[0]:
        return None
    return (parts[0], parts[1:])


def message_room(frame):
    """Room carrier of a `message` frame; None when absent."""
    value = frame_get(frame, "room_id", "room", "roomId", "channel")
    if value is None:
        return None
    if isinstance(value, str):
        return value if value else None
    return str(value)


def message_thread(frame):
    """Thread carrier of a `message` frame; None when absent."""
    value = frame_get(frame, "thread_id", "thread", "threadId")
    if value is None:
        return None
    if isinstance(value, str):
        return value if value else None
    return str(value)


def message_sender(frame):
    """Sender carrier of a `message` frame; None when absent."""
    value = frame_get(frame, "sender", "sender_name", "actor", "user_id")
    if value is None:
        return None
    if isinstance(value, str):
        return value if value else None
    try:
        text = str(value)
    except Exception:
        return None
    return text if text else None
