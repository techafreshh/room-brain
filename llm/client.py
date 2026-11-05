"""Swappable LLM entry point on OpenRouter with keyword-only fallback.

Single `llm(prompt, json_mode=False)` built on the synchronous `openai` SDK
pointed at `https://openrouter.ai/api/v1`. The model comes from `LLM_MODEL`
and the key from `OPENROUTER_API_KEY`, both read at call time. Every failure
(missing key, missing dependency, transport/API/timeout error, unparseable
JSON) raises `LLMUnavailable` so callers degrade to keyword-only. The
missing-key check runs before any import or network use.
"""

import json
import os

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
LLM_TIMEOUT = 20.0
DEFAULT_MODEL = "openai/gpt-4o-mini"


class LLMUnavailable(Exception):
    """The LLM cannot serve this call; the caller must use keyword-only."""


def _strip_fences(text):
    """Remove optional markdown fences around a JSON payload."""
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    return stripped


def llm(prompt, json_mode=False):
    """Call the LLM once; plain mode returns str, json_mode returns dict.

    Raises LLMUnavailable on any failure so callers fall back to
    keyword-only. Never retries: the client is built with max_retries=0
    so a hanging stub surfaces within the timeout bound.
    """
    key = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
    if not key:
        raise LLMUnavailable("OPENROUTER_API_KEY is not set")
    try:
        import openai
    except ImportError as exc:
        raise LLMUnavailable("openai dependency is not installed") from exc
    try:
        base_url = (
            os.environ.get("OPENROUTER_BASE_URL") or OPENROUTER_BASE_URL
        )
        model = (os.environ.get("LLM_MODEL") or "").strip() or DEFAULT_MODEL
        client = openai.OpenAI(
            api_key=key,
            base_url=base_url,
            timeout=LLM_TIMEOUT,
            max_retries=0,
        )
        kwargs = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        completion = client.chat.completions.create(**kwargs)
        content = completion.choices[0].message.content
        if isinstance(content, dict):
            parsed = content
        elif json_mode:
            parsed = json.loads(_strip_fences(str(content or "")))
        else:
            return str(content or "")
        if not isinstance(parsed, dict):
            raise LLMUnavailable("LLM JSON response is not an object")
        return parsed
    except LLMUnavailable:
        raise
    except Exception as exc:
        raise LLMUnavailable("LLM call failed: %s" % exc) from exc
