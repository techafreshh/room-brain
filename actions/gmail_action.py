"""Gmail send helper behind the approval gate (never raises)."""

import base64
import os

GMAIL_API_BASE_URL = "https://gmail.googleapis.com"
GMAIL_TIMEOUT = 5.0


def credentials_present():
    """True only when a Gmail OAuth token is configured."""
    return bool((os.environ.get("GMAIL_OAUTH_TOKEN") or "").strip())


def _api_base():
    override = (os.environ.get("GMAIL_API_BASE_URL") or "").strip()
    return (override or GMAIL_API_BASE_URL).rstrip("/")


def _build_raw(topic, body):
    """Minimal Subject + text-body MIME, base64url-encoded for messages.send."""
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["Subject"] = topic
    msg.set_content(body)
    return base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")


def send_draft(draft, client=None):
    """Best-effort Gmail send of an approved draft; never raises.

    Returns the Gmail message id on success, otherwise a falsy value.
    Returns immediately when the token is missing (zero network); otherwise
    one short-timeout attempt. A caller-supplied httpx client is used
    as-is and never closed here.
    """
    if not credentials_present():
        return False
    try:
        draft = draft or {}
        token = (os.environ.get("GMAIL_OAUTH_TOKEN") or "").strip()
        topic = str(draft.get("topic", "") or "")
        body = str(draft.get("body", "") or "")
        try:
            raw = _build_raw(topic, body)
        except Exception:
            return False
        url = _api_base() + "/gmail/v1/users/me/messages/send"
        owned = client is None
        if owned:
            import httpx

            client = httpx.Client(timeout=GMAIL_TIMEOUT)
        try:
            response = client.post(
                url,
                headers={"Authorization": "Bearer %s" % token},
                json={"raw": raw},
                timeout=GMAIL_TIMEOUT,
            )
            code = getattr(response, "status_code", 0) or 0
            if not 200 <= code < 300:
                return False
            try:
                payload = response.json()
            except Exception:
                return False
            if not isinstance(payload, dict):
                return False
            message_id = str(
                payload.get("id") or payload.get("threadId") or ""
            ).strip()
            return message_id or False
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
