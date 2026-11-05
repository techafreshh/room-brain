"""Switch ops discovery and post_message invoke (sync httpx).

The WebSocket is inbound-only, so replies go out over HTTP:
POST /agents/{id}/ops/post_message with X-Switch-Connection-Id.
Both helpers mirror register_agent's injectable-client pattern: a
caller-supplied httpx client is used as-is and never closed here.
"""

from urllib.parse import quote


def _headers(api_key, connection_id):
    """Auth + connection headers for every ops call."""
    headers = {}
    if api_key:
        headers["Authorization"] = "Bearer %s" % api_key
    if connection_id:
        headers["X-Switch-Connection-Id"] = str(connection_id)
    return headers


def discover_ops(server, agent_id, api_key, connection_id, client=None):
    """GET /agents/{id}/ops and return the operations dict.

    Never raises on a missing post_message key: any error, non-dict
    payload, or non-dict operations value yields {}.
    """
    url = server.rstrip("/") + "/agents/%s/ops" % quote(
        str(agent_id), safe=""
    )
    headers = _headers(api_key, connection_id)
    owned = client is None
    if owned:
        import httpx

        client = httpx.Client(timeout=10.0)
    try:
        try:
            response = client.get(url, headers=headers)
            response.raise_for_status()
            payload = response.json()
        except Exception:
            return {}
        if not isinstance(payload, dict):
            return {}
        ops = payload.get("operations")
        return ops if isinstance(ops, dict) else {}
    finally:
        if owned:
            try:
                client.close()
            except Exception:
                pass


def post_message(server, agent_id, api_key, connection_id, room_id,
                 text, client=None):
    """POST /agents/{id}/ops/post_message with the reply text.

    The arguments object itself is the JSON body; alias keys are sent
    so wire-unconfirmed shapes still carry the room and the text.
    Returns the result field when the response is a dict carrying it.
    """
    url = server.rstrip("/") + "/agents/%s/ops/post_message" % quote(
        str(agent_id), safe=""
    )
    headers = _headers(api_key, connection_id)
    body = {
        "room_id": room_id,
        "room": room_id,
        "content": text,
        "body": text,
        "text": text,
    }
    owned = client is None
    if owned:
        import httpx

        client = httpx.Client(timeout=10.0)
    try:
        response = client.post(url, json=body, headers=headers)
        response.raise_for_status()
        try:
            payload = response.json()
        except Exception:
            return None
        if isinstance(payload, dict) and "result" in payload:
            return payload["result"]
        return payload
    finally:
        if owned:
            try:
                client.close()
            except Exception:
                pass


def post_standalone_message(server, agent_id, api_key, room_id, text,
                             connection_id=None, client=None):
    """POST /agents/{id}/message with the reply text (no WS required).

    The arguments object itself is the JSON body; alias keys are sent
    so wire-unconfirmed shapes still carry the room and the text.
    Authorization is always sent; X-Switch-Connection-Id only when a
    connection id is supplied (live loop), omitted by the CLI.
    Returns the result field when the response is a dict carrying it.
    """
    url = server.rstrip("/") + "/agents/%s/message" % quote(
        str(agent_id), safe=""
    )
    headers = {}
    if api_key:
        headers["Authorization"] = "Bearer %s" % api_key
    if connection_id:
        headers["X-Switch-Connection-Id"] = str(connection_id)
    body = {
        "room_id": room_id,
        "room": room_id,
        "content": text,
        "body": text,
        "text": text,
    }
    owned = client is None
    if owned:
        import httpx

        client = httpx.Client(timeout=10.0)
    try:
        response = client.post(url, json=body, headers=headers)
        response.raise_for_status()
        try:
            payload = response.json()
        except Exception:
            return None
        if isinstance(payload, dict) and "result" in payload:
            return payload["result"]
        return payload
    finally:
        if owned:
            try:
                client.close()
            except Exception:
                pass
