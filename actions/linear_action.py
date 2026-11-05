"""Linear create helper behind the approval gate (never raises)."""

import os

LINEAR_API_URL = "https://api.linear.app/graphql"
LINEAR_TIMEOUT = 5.0

_ISSUE_CREATE_QUERY = (
    "mutation($input: IssueCreateInput!) {"
    " issueCreate(input: $input)"
    " { success issue { id identifier title url } } }"
)


def credentials_present():
    """True only when a Linear API key is configured."""
    return bool((os.environ.get("LINEAR_API_KEY") or "").strip())


def _api_url():
    override = (os.environ.get("LINEAR_API_URL") or "").strip()
    return override or LINEAR_API_URL


def create_issue(draft, client=None):
    """Best-effort Linear issue create of an approved draft; never raises.

    Returns the issue identifier (falling back to id/url) on success,
    otherwise a falsy value. Returns immediately when the key is missing
    (zero network); otherwise one short-timeout attempt. A caller-supplied
    httpx client is used as-is and never closed here.
    """
    if not credentials_present():
        return False
    try:
        draft = draft or {}
        key = (os.environ.get("LINEAR_API_KEY") or "").strip()
        topic = str(draft.get("topic", "") or "")
        body = str(draft.get("body", "") or "")
        team_id = (os.environ.get("LINEAR_TEAM_ID") or "").strip()
        url = _api_url()
        issue_input = {"title": topic, "description": body}
        if team_id:
            issue_input["teamId"] = team_id
        owned = client is None
        if owned:
            import httpx

            client = httpx.Client(timeout=LINEAR_TIMEOUT)
        try:
            response = client.post(
                url,
                headers={"Authorization": key},
                json={
                    "query": _ISSUE_CREATE_QUERY,
                    "variables": {"input": issue_input},
                },
                timeout=LINEAR_TIMEOUT,
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
            if payload.get("errors"):
                return False
            data = payload.get("data")
            if not isinstance(data, dict):
                return False
            result = data.get("issueCreate")
            if not isinstance(result, dict):
                return False
            if result.get("success") is not True:
                return False
            issue = result.get("issue")
            if not isinstance(issue, dict):
                return False
            for field in ("identifier", "id", "url"):
                value = str(issue.get(field) or "").strip()
                if value:
                    return value
            return False
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
