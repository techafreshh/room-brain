"""Linear create helper behind the approval gate (never raises)."""

import os


def credentials_present():
    """True only when a Linear API key is configured."""
    return bool((os.environ.get("LINEAR_API_KEY") or "").strip())


def create_issue(draft, client=None):
    """Best-effort Linear issue create of an approved draft; never raises.

    Returns False immediately when the key is missing; otherwise one
    short-timeout attempt, True on success and False on any failure.
    A caller-supplied httpx client is used as-is and never closed here.
    """
    if not credentials_present():
        return False
    try:
        draft = draft or {}
        key = (os.environ.get("LINEAR_API_KEY") or "").strip()
        topic = str(draft.get("topic", "") or "")
        body = str(draft.get("body", "") or "")
        owned = client is None
        if owned:
            import httpx

            client = httpx.Client(timeout=5.0)
        try:
            response = client.post(
                "https://api.linear.app/graphql",
                headers={"Authorization": key},
                json={
                    "query": "mutation($t:String!,$d:String){"
                    "issueCreate(input:{title:$t,description:$d})"
                    "{success}}",
                    "variables": {"t": topic, "d": body},
                },
                timeout=5.0,
            )
            code = getattr(response, "status_code", 0) or 0
            return 200 <= code < 300
        except Exception:
            return False
        finally:
            if owned:
                try:
                    client.close()
                except Exception:
                    pass
    except Exception:
        return False
