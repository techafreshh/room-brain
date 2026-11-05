"""Injection guard: wrap untrusted chat text before any LLM call.

Chat text is untrusted and must never survive as instructions. clean()
wraps the text in literal <untrusted> delimiters and replaces
instruction-shaped lines with a stripped: marker, so a line like
"Ignore previous instructions ..." can never reach the model verbatim.
"""

from __future__ import annotations

import re

UNTRUSTED_OPEN = "<untrusted>"
UNTRUSTED_CLOSE = "</untrusted>"

STRIPPED_MARKER = "stripped: %d instruction-shaped line(s) removed"

INSTRUCTION_PATTERNS = (
    re.compile(
        r"(ignore|disregard|forget|override|bypass|disable)\b"
        r".*\b(instructions?|prompts?|rules?|directives?|guidelines?)",
        re.IGNORECASE,
    ),
    re.compile(r"^system\s*:", re.IGNORECASE),
    re.compile(r"^\[?system\]?\s*:", re.IGNORECASE),
    re.compile(r"^\[?system\]?$", re.IGNORECASE),
    re.compile(r"^you are\b", re.IGNORECASE),
    re.compile(r"^as an (ai|llm|language model)\b", re.IGNORECASE),
    re.compile(r"^<\s*/?\s*system\b", re.IGNORECASE),
    re.compile(
        r"^(execute|run|disregard)\b.*instructions?", re.IGNORECASE
    ),
)


def _is_instruction_line(line):
    """True when a single line looks like an injected instruction."""
    stripped = line.strip()
    if not stripped:
        return False
    return any(pattern.search(stripped) for pattern in INSTRUCTION_PATTERNS)


def clean(text):
    """Wrap text in <untrusted> delimiters, dropping instruction lines.

    Instruction-shaped lines are replaced by a single
    "stripped: N instruction-shaped line(s) removed" marker line.
    None and non-string input yield a wrapped empty string; never raises.
    """
    if text is None:
        text = ""
    elif not isinstance(text, str):
        try:
            text = str(text)
        except Exception:
            text = ""
    kept = []
    dropped = 0
    for line in text.splitlines():
        if _is_instruction_line(line):
            dropped += 1
        else:
            kept.append(line)
    body_lines = []
    if dropped:
        body_lines.append(STRIPPED_MARKER % dropped)
    body_lines.extend(kept)
    return "%s\n%s\n%s" % (
        UNTRUSTED_OPEN,
        "\n".join(body_lines),
        UNTRUSTED_CLOSE,
    )
