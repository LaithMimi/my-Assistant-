"""
Telegram bot command handlers for the AI CEO Assistant.

Phase 2 enhancements (Google AI Best Practices):
  - Input sanitization via utils.sanitizer before every agent call
  - Confirmation protocol: intercepts "yes"/"no" replies BEFORE agent invocation
  - Graceful error handling with user-friendly Telegram messages
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import defaultdict

from telegram import Update
from telegram.constants import ChatAction as CA
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from ceo_assistant.agent import run_agent
from ceo_assistant.google.auth import build_auth_url, get_user_name, is_authorised
from ceo_assistant.memory import get_memory_manager
from ceo_assistant.utils import confirmation as confirm_mgr
from ceo_assistant.utils.sanitizer import sanitize_input
from ceo_assistant.utils.splitter import split_message

logger = logging.getLogger(__name__)

# ── CEO profile store ─────────────────────────────────────────────────────
_ceo_profiles: dict[int, dict] = {}

DEFAULT_PROFILE = {
    "name": "CEO",
    "company": "your company",
    "stage": "early",
    "focus_areas": "growth, product, team",
    "style": "direct and concise",
}


def get_profile(chat_id: int) -> dict:
    return _ceo_profiles.get(chat_id, DEFAULT_PROFILE.copy())


# ── Yes/No keyword recognisers ─────────────────────────────────────────────
_YES_WORDS = frozenset(["yes", "y", "confirm", "ok", "sure", "do it", "proceed", "go ahead", "yep", "yeah"])
_NO_WORDS = frozenset(["no", "n", "cancel", "skip", "stop", "nope", "nah", "abort"])

import re

def _is_yes(text: str) -> bool:
    clean = text.lower().strip().rstrip("!.")
    if clean in _YES_WORDS:
        return True
    # If the user says "yes do it" or "yes mark as complete"
    return any(clean.startswith(w + " ") for w in _YES_WORDS)


def _is_no(text: str) -> bool:
    clean = text.lower().strip().rstrip("!.")
    if clean in _NO_WORDS:
        return True
    return any(clean.startswith(w + " ") for w in _NO_WORDS)


# ── Rate limiting ─────────────────────────────────────────────────────────

_rate_limits = defaultdict(list)

def _is_rate_limited(chat_id: int, max_calls: int = 15, window_seconds: int = 60) -> bool:
    """True if chat_id has made >= max_calls within window_seconds."""
    now = time.time()
    calls = [t for t in _rate_limits[chat_id] if now - t < window_seconds]
    _rate_limits[chat_id] = calls
    if len(calls) >= max_calls:
        return True
    _rate_limits[chat_id].append(now)
    return False


# ── Core helpers ──────────────────────────────────────────────────────────

async def _send_chunks(context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str) -> None:
    for chunk in split_message(text):
        await context.bot.send_message(chat_id=chat_id, text=chunk, parse_mode="HTML")


async def _thinking_and_run(
    update: Update, context: ContextTypes.DEFAULT_TYPE, user_message: str
) -> None:
    """Sanitize → show thinking → run agent → edit with result."""
    chat_id = update.effective_chat.id

    if _is_rate_limited(chat_id):
        await update.effective_message.reply_text(
            "⚠️ <b>Rate limit exceeded.</b> Please wait a minute before sending more requests.",
            parse_mode="HTML"
        )
        return

    if not is_authorised(chat_id):
        auth_url = build_auth_url(chat_id)
        await update.effective_message.reply_text(
            f"🔐 <b>Google not connected yet.</b>\n\n"
            f'Please authorise: <a href="{auth_url}">👉 Connect Google Account</a>',
            parse_mode="HTML",
        )
        return

    await context.bot.send_chat_action(chat_id=chat_id, action=CA.TYPING)
    thinking_msg = await update.effective_message.reply_text("⏳ Thinking…")

    try:
        profile = get_profile(chat_id)
        result = await run_agent(chat_id, profile, user_message)

        chunks = split_message(result)
        if chunks:
            await thinking_msg.edit_text(chunks[0], parse_mode="HTML")
            for chunk in chunks[1:]:
                await context.bot.send_message(chat_id=chat_id, text=chunk, parse_mode="HTML")
        else:
            await thinking_msg.edit_text("✅ Done.")
    except Exception as exc:
        logger.error("Agent error for chat_id=%s: %s", chat_id, exc, exc_info=True)
        await thinking_msg.edit_text(
            f"⚠️ <b>Something went wrong.</b>\n<code>{str(exc)[:200]}</code>",
            parse_mode="HTML",
        )


# ── Command handlers ──────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    auth_url = build_auth_url(chat_id)

    if is_authorised(chat_id):
        name = get_user_name(chat_id)
        # Check if they just sent /start to get the menu
        await update.message.reply_text(
            f"✅ <b>Welcome back, {name}! You're already connected.</b>\n\n"
            "I'm your AI Chief of Staff. Commands:\n"
            "• /triage — Inbox triage\n"
            "• /brief — Pre-meeting briefing\n"
            "• /tasks — View tasks\n"
            "• /schedule — Book a meeting\n"
            "• /research — Web research\n"
            "• /protect — Block focus time\n"
            "• /remember — Save memory\n"
            "• /recall — Search memory\n\n"
            "Or just <b>send me a message</b> — I'll handle it. 🚀",
            parse_mode="HTML",
        )
    else:
        await update.message.reply_text(
            f"👋 <b>Hello! I'm your AI Chief of Staff.</b>\n\n"
            f"First, connect your Google account:\n"
            f'<a href="{auth_url}">👉 Connect Google Account</a>\n\n'
            f"Once authorised, send /start again.",
            parse_mode="HTML",
        )


async def triage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _thinking_and_run(update, context, "Triage my inbox — fetch and classify my last 20 unread emails by priority.")


async def brief(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _thinking_and_run(update, context, "Generate a pre-meeting briefing for my next calendar event.")


async def schedule(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = " ".join(context.args) if context.args else ""
    msg = f"Schedule this meeting: {args}" if args else "Help me book a meeting — ask me for the details."
    await _thinking_and_run(update, context, msg)


async def tasks_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _thinking_and_run(update, context, "Show me all my open tasks.")


async def addtask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = " ".join(context.args) if context.args else ""
    msg = f"Add a new task: {args}" if args else "I want to add a task — ask me for the details."
    await _thinking_and_run(update, context, msg)


async def research(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = " ".join(context.args) if context.args else ""
    if not query:
        await update.message.reply_text("🔍 What should I research? E.g. /research Series A trends 2025")
        return
    await _thinking_and_run(update, context, f"Research this topic for me: {query}")


async def protect(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = " ".join(context.args) if context.args else ""
    msg = f"Block focus time on my calendar. {args}" if args else "Help me block focus time — ask for date and duration."
    await _thinking_and_run(update, context, msg)


async def remember(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    note = " ".join(context.args) if context.args else ""
    if not note:
        await update.message.reply_text(
            "🧠 What should I save? E.g. /remember Investor John prefers async email updates"
        )
        return
    await _thinking_and_run(update, context, f"Save this to my memory: {note}")


async def recall(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = " ".join(context.args) if context.args else ""
    if not query:
        await update.message.reply_text("🧠 What do you want to recall? E.g. /recall investor preferences")
        return
    await _thinking_and_run(update, context, f"Search my memory for: {query}")


# ── Free-text handler (with confirmation intercept) ───────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Primary message handler.

    Priority order:
      1. If there is a PENDING CONFIRMATION and the message is yes/no → handle it.
      2. Otherwise → sanitize + run agent.
    """
    raw_text = update.message.text or ""
    chat_id = update.effective_chat.id

    # ── Confirmation intercept ────────────────────────────────────────────
    if confirm_mgr.has_pending(chat_id):
        if _is_yes(raw_text):
            await context.bot.send_chat_action(chat_id=chat_id, action=CA.TYPING)
            result = await confirm_mgr.confirm(chat_id)
            for chunk in split_message(result):
                await update.message.reply_text(chunk, parse_mode="HTML")
            return
        elif _is_no(raw_text):
            result = confirm_mgr.cancel(chat_id)
            await update.message.reply_text(result, parse_mode="HTML")
            return
        else:
            # User sent something else while a confirmation is pending
            confirm_mgr.cancel(chat_id)
            await update.message.reply_text(
                "⚠️ Pending action cancelled (you sent a new message).\n\n"
                "Handling your new request now…",
                parse_mode="HTML",
            )
            # Fall through to agent

    # ── Normal agent flow ─────────────────────────────────────────────────
    clean = sanitize_input(raw_text)
    if not clean:
        return
    await _thinking_and_run(update, context, clean)


async def sync(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not is_authorised(chat_id):
        await update.message.reply_text("⚠️ Please /start to connect your Google account first.")
        return
    if _is_rate_limited(chat_id, max_calls=15, window_seconds=60):
        await update.message.reply_text("⚠️ You're chatting too fast! Please wait a minute.")
        return

    msg = await update.message.reply_text("⏳ Syncing your latest Google Docs and Startup Context...")
    try:
        from ceo_assistant.memory import MemoryManager
        memory_mgr = MemoryManager(chat_id)
        # This will download the CEO doc + external doc and rebuild the FAISS index
        memory_mgr.build_index()
        await msg.edit_text("✅ <b>Sync complete!</b> Your bot now has the latest documents in memory.", parse_mode="HTML")
    except Exception as exc:
        logger.error("Sync error for chat_id=%s: %s", chat_id, exc)
        await msg.edit_text(f"⚠️ Failed to sync documents: <code>{exc}</code>", parse_mode="HTML")


# ── Application builder ───────────────────────────────────────────────────

def create_application(token: str) -> Application:
    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("triage", triage))
    app.add_handler(CommandHandler("brief", brief))
    app.add_handler(CommandHandler("schedule", schedule))
    app.add_handler(CommandHandler("tasks", tasks_cmd))
    app.add_handler(CommandHandler("addtask", addtask))
    app.add_handler(CommandHandler("research", research))
    app.add_handler(CommandHandler("protect", protect))
    app.add_handler(CommandHandler("remember", remember))
    app.add_handler(CommandHandler("recall", recall))
    app.add_handler(CommandHandler("sync", sync))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    return app
