"""
In-process pending action registry for human-in-the-loop confirmation.

Pattern (Google Agent Whitepaper — "Confirmation Protocol"):
  1. Tool builds a preview and registers an async callback here
  2. Tool returns a confirmation request string to the agent
  3. Agent passes string to user via Telegram
  4. bot.py intercepts "yes"/"no" replies BEFORE calling the agent
  5. "yes"  → execute(), return result to CEO
     "no"   → cancel(), inform CEO

No database needed — confirmations are ephemeral, per-chat, in-memory.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

# chat_id → PendingAction
_registry: dict[int, "_PendingAction"] = {}


from datetime import datetime, timedelta

class _PendingAction:
    __slots__ = ("label", "preview", "execute_fn", "expires_at")

    def __init__(
        self,
        label: str,
        preview: str,
        execute_fn: Callable[[], Awaitable[str]],
    ) -> None:
        self.label = label
        self.preview = preview
        self.execute_fn = execute_fn
        self.expires_at = datetime.now() + timedelta(minutes=5)


def register(
    chat_id: int,
    label: str,
    preview: str,
    execute_fn: Callable[[], Awaitable[str]],
) -> str:
    """
    Register a pending action and return the confirmation prompt string.

    Args:
        chat_id:    Telegram chat ID
        label:      Short human-readable action name, e.g. "Create calendar event"
        preview:    Full detail of what will be executed (shown to CEO)
        execute_fn: Async callable that performs the actual action

    Returns:
        A formatted Telegram HTML string asking for confirmation.
    """
    _registry[chat_id] = _PendingAction(label, preview, execute_fn)
    logger.info("Pending confirmation registered for chat_id=%s: %s", chat_id, label)
    return (
        f"⚠️ <b>Action requires confirmation</b>\n\n"
        f"I'm about to: <b>{label}</b>\n\n"
        f"{preview}\n\n"
        f"Reply <b>yes</b> to confirm or <b>no</b> to cancel."
    )


def has_pending(chat_id: int) -> bool:
    """Return True if a confirmation is waiting for this chat_id."""
    return chat_id in _registry


async def confirm(chat_id: int) -> str:
    """Execute the pending action and remove it from the registry."""
    action = _registry.pop(chat_id, None)
    if action is None:
        return "⚠️ No pending action found."
    
    if datetime.now() > action.expires_at:
        return "⏰ Action expired. Please try again."

    logger.info("Executing confirmed action for chat_id=%s: %s", chat_id, action.label)
    try:
        result = await action.execute_fn()
        return result
    except Exception as exc:
        logger.error("Confirmed action failed for chat_id=%s: %s", chat_id, exc)
        return f"⚠️ Action failed: {exc}"


def cancel(chat_id: int) -> str:
    """Cancel the pending action."""
    action = _registry.pop(chat_id, None)
    if action:
        logger.info("Action cancelled for chat_id=%s: %s", chat_id, action.label)
        return f"❌ Cancelled: <i>{action.label}</i>\n\nAnything else?"
    return "No pending action to cancel."
