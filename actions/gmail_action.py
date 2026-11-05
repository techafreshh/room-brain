"""Gmail send helper behind the approval gate (never raises)."""

import os


def credentials_present():
    """True only when a Gmail OAuth token is configured."""
    return bool((os.environ.get("GMAIL_OAUTH_TOKEN") or "").strip())


def send_draft(draft, client=None):
    """Best-effort Gmail send of an approved draft; never raises.

    Returns False immediately when the token is missing; otherwise one
    short-timeout attempt, True on success and False on any failure.
    A caller-supplied httpx client is used as-is and never closed here.
    """
    if not credentials_present():
        return False
    try:
        draft = draft or {}
        token = (os.environ.get("GMAIL_OAUTH_TOKEN") or "").strip()
        topic = str(draft.get("topic", "") or "")
        body = str(draft.get("body", "") or "")
        owned = client is None
        if owned:
            import httpx

            client = httpx.Client(timeout=5.0)
        try:
            response = client.post(
                "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
                headers={"Authorization": "Bearer %s" % token},
                json={"raw": body, "subject": topic},
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
