"""
Input sanitization for Telegram messages before passing to the LLM.

Per Google AgentOps security recommendations:
- Strip control characters
- Remove hidden unicode (zero-width, directional overrides, etc.)
- Normalize whitespace
- Enforce max length to prevent prompt injection via mega-messages
"""

from __future__ import annotations

import re
import unicodedata

MAX_INPUT_LENGTH = 4000  # chars — prevents prompt injection via massive messages

# Unicode categories to strip:
# Cc = control chars, Cf = format chars (incl. RTL/LTR overrides, zero-width)
_STRIP_CATEGORIES = {"Cc", "Cf"}

# Additional explicit codepoints to always remove
_STRIP_CHARS = frozenset(
    [
        "\u200b",  # zero-width space
        "\u200c",  # zero-width non-joiner
        "\u200d",  # zero-width joiner
        "\u200e",  # left-to-right mark
        "\u200f",  # right-to-left mark
        "\u202a",  # left-to-right embedding
        "\u202b",  # right-to-left embedding
        "\u202c",  # pop directional formatting
        "\u202d",  # left-to-right override
        "\u202e",  # right-to-left override (common injection vector)
        "\u2060",  # word joiner
        "\u2061",  # function application
        "\u2062",  # invisible times
        "\u2063",  # invisible separator
        "\u2064",  # invisible plus
        "\ufeff",  # BOM / zero-width no-break space
    ]
)


def sanitize_input(text: str) -> str:
    """
    Sanitize a user-supplied Telegram message for safe LLM processing.

    - Strips control characters and invisible unicode
    - Removes directional override characters (RTL injection vectors)
    - Normalizes whitespace (multiple spaces → single, strips leading/trailing)
    - Truncates to MAX_INPUT_LENGTH

    Returns the cleaned string.
    """
    if not text:
        return ""

    # 1. NFKC normalization — collapses look-alike characters
    text = unicodedata.normalize("NFKC", text)

    # 2. Strip dangerous unicode categories and explicit chars
    cleaned_chars: list[str] = []
    for ch in text:
        cp = unicodedata.category(ch)
        if cp in _STRIP_CATEGORIES or ch in _STRIP_CHARS:
            continue
        # Keep newlines and tabs (Cc but safe)
        if ch in ("\n", "\t", "\r"):
            cleaned_chars.append(ch)
            continue
        cleaned_chars.append(ch)
    text = "".join(cleaned_chars)

    # 3. Collapse multiple blank lines to at most two
    text = re.sub(r"\n{3,}", "\n\n", text)

    # 4. Strip leading/trailing whitespace
    text = text.strip()

    # 5. Truncate with a warning suffix
    if len(text) > MAX_INPUT_LENGTH:
        text = text[:MAX_INPUT_LENGTH] + " [truncated]"

    return text
