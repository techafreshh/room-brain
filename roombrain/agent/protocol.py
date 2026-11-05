"""Switch registration protocol: POST /agents and .env persistence.

The .env file is the source of truth for the agent id and api_key. The api_key
is returned only once at registration, so it is persisted immediately and the
register flow never re-registers while both values are stored. A 409 on name
reuse means another registration already owns the name: reuse the stored key
and never retry with overwrite.
"""

import asyncio
import json
import os
import uuid
from urllib.parse import quote, urlencode, urlparse, urlunparse

AGENT_ID_KEY = "ROOMBRAIN_AGENT_ID"
API_KEY_KEY = "ROOMBRAIN_API_KEY"
CONNECTION_ID_KEY = "ROOMBRAIN_CONNECTION_ID"
ROOMS_KEY = "ROOMBRAIN_ROOMS"


class RegistrationConflict(Exception):
    """The server answered 409: the name is taken, reuse the stored key."""


class TakenOver(Exception):
    """The server evicted this connection (taken_over): exit, never retry."""


def read_env_values(path):
    """Parse KEY=VALUE lines from an env file; missing file yields {}."""
    values = {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
    except OSError:
        return {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key or key.startswith("#"):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        values[key] = value
    return values


def write_env_values(path, mapping):
    """Replace-or-append mapping keys, preserving all other lines.

    Creates the file when missing. The write is atomic (temp file + rename)
    so a crash never leaves a half-written .env behind.
    """
    path = os.fspath(path)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            existing = handle.read().splitlines()
    except FileNotFoundError:
        existing = None
    pending = dict(mapping)
    out = []
    if existing is not None:
        for line in existing:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in line:
                key = line.split("=", 1)[0].strip()
                if key in pending:
                    out.append("%s=%s" % (key, pending.pop(key)))
                    continue
            out.append(line)
    for key, value in mapping.items():
        if key in pending:
            out.append("%s=%s" % (key, value))
    tmp_path = "%s.tmp" % path
    with open(tmp_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(out) + "\n")
    os.replace(tmp_path, path)
    return dict(mapping)


def build_registration_body(name):
    """Request body for POST /agents (never includes overwrite)."""
    return {
        "name": name,
        "description": "RoomBrain team memory agent",
        "connector_type": "roombrain",
        "integration_profile": {
            "connection_model": "always_on",
            "message_exchange": True,
            "pre_invocation_mediation": [],
            "post_invocation_mediation": [],
            "event_reporting": [],
        },
    }


def register_agent(server, token, name, env_path=".env", client=None):
    """Register once via POST /agents and persist the returned credentials.

    Returns (agent_id, api_key, reused) with reused False on a fresh 200.
    Raises RegistrationConflict on HTTP 409 without touching .env.
    A caller-supplied httpx client is used as-is (never closed here); when
    omitted, a short-lived client is built and closed around the single POST.
    """
    body = build_registration_body(name)
    headers = {}
    if token:
        headers["Authorization"] = "Bearer %s" % token
    url = server.rstrip("/") + "/agents"
    owned = client is None
    if owned:
        import httpx

        client = httpx.Client(timeout=10.0)
    try:
        response = client.post(url, json=body, headers=headers)
        if response.status_code == 409:
            raise RegistrationConflict(
                "agent name %r already registered; reusing stored key" % (name,)
            )
        response.raise_for_status()
        payload = response.json()
        agent_id = payload["id"]
        api_key = payload["api_key"]
    finally:
        if owned:
            client.close()
    if not agent_id or not api_key:
        raise ValueError("register: server response missing id/api_key")
    write_env_values(env_path, {AGENT_ID_KEY: agent_id, API_KEY_KEY: api_key})
    return agent_id, api_key, False


def build_ws_url(
    server, agent_id, connection_id, rooms, start_from=None,
    expected_generation=None,
):
    """WebSocket URL for GET /agents/{id}/connection/ws.

    Query always carries connection_id + rooms; reconnects add
    start_from + expected_generation fencing (never sent on first open).
    """
    parsed = urlparse(server)
    scheme = {"http": "ws", "https": "wss"}.get(parsed.scheme, parsed.scheme)
    if isinstance(rooms, (list, tuple)):
        rooms = ",".join(str(room) for room in rooms)
    query = [
        ("connection_id", str(connection_id)),
        ("rooms", str(rooms or "")),
    ]
    if start_from is not None:
        query.append(("start_from", str(start_from)))
    if expected_generation is not None:
        query.append(("expected_generation", str(expected_generation)))
    path = "/agents/%s/connection/ws" % quote(str(agent_id), safe="")
    return urlunparse((scheme, parsed.netloc, path, "", urlencode(query), ""))


def load_or_create_connection_id(env_path=".env"):
    """Stable reconnect identity: reuse the stored value, else generate
    a uuid4, persist it with write_env_values, and return it."""
    stored = (read_env_values(env_path).get(CONNECTION_ID_KEY) or "").strip()
    if stored:
        return stored
    fallback = (os.environ.get(CONNECTION_ID_KEY) or "").strip()
    if fallback:
        return fallback
    connection_id = str(uuid.uuid4())
    write_env_values(env_path, {CONNECTION_ID_KEY: connection_id})
    return connection_id


async def run_forever(
    server,
    agent_id,
    api_key,
    rooms,
    connection_id=None,
    env_path=".env",
    connect_fn=None,
    first_frame_timeout=10.0,
    max_backoff=30.0,
):
    """Always-on connect loop: ping/pong, fencing reconnect, taken_over exit.

    Opens the connection with a Bearer handshake, answers every `ping`
    with `{"type": "pong", "cursor": N}` before any dispatch, advances
    one monotonic cursor over every sequence/seq/cursor frame, and on any
    abnormal close reopens with the same connection_id plus
    start_from=cursor and expected_generation=generation. A `taken_over`
    eviction raises TakenOver (terminal: the caller exits 3, never retry).
    A caller-supplied connect_fn(url) (async context manager yielding a
    send/recv/close socket) is used as-is; otherwise a websockets client
    with ping_interval=None is built per attempt.
    """
    from websockets.asyncio.client import connect as _ws_connect
    from websockets.exceptions import ConnectionClosed, WebSocketException

    from roombrain.agent.events import (
        advance_cursor,
        frame_type,
        is_taken_over,
        message_body,
        message_room,
        message_sender,
        message_thread,
        parse_command,
        parse_connection_state,
        parse_frame,
    )
    from roombrain.agent.ops import post_message

    cid = connection_id or load_or_create_connection_id(env_path)
    if isinstance(rooms, (list, tuple)):
        rooms_str = ",".join(str(room) for room in rooms)
    else:
        rooms_str = str(rooms or "")
    if connect_fn is None:
        def connect_fn(url):  # noqa: F811 - default opener, closed by ws
            return _ws_connect(
                url,
                additional_headers={"Authorization": "Bearer %s" % api_key},
                ping_interval=None,
            )

    cursor = 0
    generation = None
    attempts = 0
    while True:
        if attempts:
            delay = 0.0 if attempts == 1 else min(
                float(max_backoff), float(2 ** (attempts - 2))
            )
            if delay > 0:
                await asyncio.sleep(delay)
        if generation is None:
            url = build_ws_url(server, agent_id, cid, rooms_str)
        else:
            url = build_ws_url(
                server,
                agent_id,
                cid,
                rooms_str,
                start_from=cursor,
                expected_generation=generation,
            )
        try:
            async with connect_fn(url) as ws:
                try:
                    raw = await asyncio.wait_for(
                        ws.recv(), timeout=first_frame_timeout
                    )
                except asyncio.TimeoutError:
                    try:
                        await ws.close()
                    except Exception:
                        pass
                    attempts += 1
                    continue
                frame = parse_frame(raw)
                if is_taken_over(frame):
                    raise TakenOver(
                        "connection taken over (evicted: taken_over)"
                    )
                state = parse_connection_state(frame)
                if state is None:
                    try:
                        await ws.close()
                    except Exception:
                        pass
                    attempts += 1
                    continue
                if state.cursor > cursor:
                    cursor = state.cursor
                generation = state.generation
                attempts = 0
                while True:
                    raw = await ws.recv()
                    frame = parse_frame(raw)
                    cursor = advance_cursor(cursor, frame)
                    ftype = frame_type(frame)
                    if ftype == "ping":
                        await ws.send(
                            json.dumps({"type": "pong", "cursor": cursor})
                        )
                        continue
                    if is_taken_over(frame):
                        raise TakenOver(
                            "connection taken over (evicted: taken_over)"
                        )
                    if ftype == "evicted":
                        break  # evicted (other code): re-establish below.
                    if ftype == "connection_state":
                        restated = parse_connection_state(frame)
                        if restated is not None:
                            if restated.cursor > cursor:
                                cursor = restated.cursor
                            if restated.generation > generation:
                                generation = restated.generation
                        continue
                    body = message_body(frame)
                    if body is not None:
                        cmd = parse_command(body)
                        if cmd is None:
                            continue
                        print(body, flush=True)
                        name, _args = cmd
                        try:
                            _room_probe = message_room(frame)
                            _sender_probe = message_sender(frame)
                            if _room_probe and _sender_probe:
                                from actions.gate import ensure_owner as _ensure_owner

                                try:
                                    _ensure_owner(_room_probe, _sender_probe)
                                except Exception:
                                    pass
                        except Exception:
                            pass
                        if name == "ping":
                            room_id = message_room(frame)
                            if not room_id:
                                if isinstance(rooms, (list, tuple)):
                                    room_id = str(rooms[0]) if rooms else ""
                                elif rooms_str:
                                    room_id = rooms_str.split(",")[0].strip()
                                else:
                                    room_id = ""
                            try:
                                await asyncio.to_thread(
                                    post_message,
                                    server,
                                    agent_id,
                                    api_key,
                                    cid,
                                    room_id,
                                    "pong",
                                )
                            except Exception:
                                pass
                        elif name in ("remember", "recall", "decisions"):
                            from roombrain.agent.commands import dispatch_command

                            room_id = message_room(frame)
                            if not room_id:
                                if isinstance(rooms, (list, tuple)):
                                    room_id = str(rooms[0]) if rooms else ""
                                elif rooms_str:
                                    room_id = rooms_str.split(",")[0].strip()
                                else:
                                    room_id = ""
                            try:
                                reply = dispatch_command(
                                    name,
                                    _args,
                                    {
                                        "room": room_id,
                                        "actor": message_sender(frame) or "",
                                        "thread_id": message_thread(frame) or "",
                                    },
                                )
                            except Exception:
                                reply = None
                            if not reply:
                                continue
                            try:
                                await asyncio.to_thread(
                                    post_message,
                                    server,
                                    agent_id,
                                    api_key,
                                    cid,
                                    room_id,
                                    reply,
                                )
                            except Exception:
                                pass
                        elif name in ("draft", "approve", "reject"):
                            from actions.gate import dispatch_gate

                            room_id = message_room(frame)
                            if not room_id:
                                if isinstance(rooms, (list, tuple)):
                                    room_id = str(rooms[0]) if rooms else ""
                                elif rooms_str:
                                    room_id = rooms_str.split(",")[0].strip()
                                else:
                                    room_id = ""
                            try:
                                reply = dispatch_gate(
                                    name,
                                    _args,
                                    {
                                        "room": room_id,
                                        "sender": message_sender(frame) or "",
                                        "requester": message_sender(frame) or "",
                                        "thread_id": message_thread(frame) or "",
                                        "agent_id": agent_id,
                                    },
                                )
                            except Exception:
                                reply = None
                            if not reply:
                                continue
                            try:
                                await asyncio.to_thread(
                                    post_message,
                                    server,
                                    agent_id,
                                    api_key,
                                    cid,
                                    room_id,
                                    reply,
                                )
                            except Exception:
                                pass
                        else:
                            continue
        except TakenOver:
            raise
        except (ConnectionClosed, WebSocketException, OSError,
                asyncio.TimeoutError):
            attempts += 1
            continue
