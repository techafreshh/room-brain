"""Switch registration protocol: POST /agents and .env persistence.

The .env file is the source of truth for the agent id and api_key. The api_key
is returned only once at registration, so it is persisted immediately and the
register flow never re-registers while both values are stored. A 409 on name
reuse means another registration already owns the name: reuse the stored key
and never retry with overwrite.
"""

import os

AGENT_ID_KEY = "ROOMBRAIN_AGENT_ID"
API_KEY_KEY = "ROOMBRAIN_API_KEY"


class RegistrationConflict(Exception):
    """The server answered 409: the name is taken, reuse the stored key."""


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
