"""
Split long Telegram messages into chunks of at most max_len characters.
Splits on newlines to avoid breaking mid-word, then falls back to hard splits.
"""

from __future__ import annotations

import re


def split_message(text: str, max_len: int = 4096) -> list[str]:
    """
    Split `text` into a list of strings each ≤ max_len characters.

    Tries to split on paragraph/newline boundaries first so formatted
    content (bullet lists, headers) stays coherent. Falls back to a
    hard character split when a single line exceeds max_len.
    """
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    current = ""

    for line in text.splitlines(keepends=True):
        # Single line longer than limit → hard split
        if len(line) > max_len:
            # flush current buffer first
            if current:
                chunks.append(current)
                current = ""
            for i in range(0, len(line), max_len):
                chunks.append(line[i : i + max_len])
            continue

        if len(current) + len(line) > max_len:
            chunks.append(current)
            current = line
        else:
            current += line

    if current:
        chunks.append(current)

    # Strip leading/trailing whitespace from each chunk
    return [c.strip() for c in chunks if c.strip()]


def truncate(text: str, max_len: int = 200, suffix: str = "…") -> str:
    """Truncate text to max_len chars with a suffix."""
    if len(text) <= max_len:
        return text
    return text[: max_len - len(suffix)] + suffix
