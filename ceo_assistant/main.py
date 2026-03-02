"""
FastAPI application — entry point for the CEO Assistant.

Endpoints:
  POST /webhook          — Telegram webhook (fire-and-forget, returns 200 immediately)
  GET  /auth             — Redirect to Google OAuth consent for a ?chat_id
  GET  /auth/callback    — OAuth callback: saves tokens, confirms via Telegram
  GET  /health           — Health check
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

load_dotenv()

# Validate required env vars early
_REQUIRED = ["TELEGRAM_BOT_TOKEN", "OPENAI_API_KEY", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"]
_missing = [k for k in _REQUIRED if not os.environ.get(k)]
if _missing:
    raise RuntimeError(f"Missing required environment variables: {', '.join(_missing)}")

# Set up LangSmith tracing before importing LangChain modules
if os.environ.get("LANGSMITH_API_KEY"):
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
    os.environ.setdefault("LANGCHAIN_PROJECT", os.environ.get("LANGSMITH_PROJECT", "ceo-assistant"))
    os.environ.setdefault("LANGCHAIN_API_KEY", os.environ["LANGSMITH_API_KEY"])

from telegram import Bot, Update

from ceo_assistant.bot import create_application
from ceo_assistant.google.auth import build_auth_url, exchange_code, get_user_name

logging.basicConfig(
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")
BASE_URL = os.environ.get("BASE_URL", "")

# ── Telegram application (shared across requests) ─────────────────────────
_tg_app = create_application(TOKEN)
_bot: Bot = _tg_app.bot


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Set the Telegram webhook on startup."""
    await _tg_app.initialize()
    if WEBHOOK_URL:
        await _bot.set_webhook(url=WEBHOOK_URL, drop_pending_updates=True)
        logger.info("Webhook set to %s", WEBHOOK_URL)
    else:
        logger.warning("WEBHOOK_URL not set — webhook not registered.")
    yield
    await _tg_app.shutdown()


app = FastAPI(title="CEO Assistant", version="1.0.0", lifespan=lifespan)


# ── Health check ─────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok", "service": "ceo-assistant"})


# ── Telegram webhook ──────────────────────────────────────────────────────

async def _process_update(raw_update: dict) -> None:
    """Process a Telegram update in the background."""
    try:
        update = Update.de_json(raw_update, _bot)
        await _tg_app.process_update(update)
    except Exception as exc:
        logger.error("Error processing update: %s", exc, exc_info=True)


@app.post("/webhook")
async def webhook(request: Request) -> JSONResponse:
    """
    Receive Telegram updates. Fire-and-forget to avoid the 10-second timeout.
    Always returns 200 immediately so Telegram doesn't retry.
    """
    try:
        body = await request.json()
        asyncio.create_task(_process_update(body))
    except Exception as exc:
        logger.error("Webhook deserialization error: %s", exc)
    return JSONResponse({"ok": True})


# ── Google OAuth flow ─────────────────────────────────────────────────────

@app.get("/auth")
async def auth_start(chat_id: int) -> RedirectResponse:
    """
    Redirect the user (from Telegram) to Google's OAuth consent screen.
    The `chat_id` is passed as the OAuth `state` parameter.
    """
    auth_url = build_auth_url(chat_id)
    return RedirectResponse(url=auth_url)


@app.get("/auth/callback")
async def auth_callback(code: str, state: str) -> HTMLResponse:
    """
    Handle the OAuth callback from Google.
    Saves tokens and sends a Telegram confirmation message.
    """
    try:
        chat_id = int(state)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid state parameter")

    try:
        creds = exchange_code(code, chat_id)
        name = get_user_name(chat_id)

        # Notify the user in Telegram
        try:
            await _bot.send_message(
                chat_id=chat_id,
                text=(
                    f"✅ <b>Google connected!</b> Welcome, {name}.\n\n"
                    "You're all set. Send /start to begin."
                ),
                parse_mode="HTML",
            )
        except Exception as tg_exc:
            logger.warning("Telegram notification failed: %s", tg_exc)

        return HTMLResponse(
            content=f"""
            <html>
              <body style="font-family:sans-serif;text-align:center;padding:60px">
                <h2>✅ Google Account Connected!</h2>
                <p>Hi <strong>{name}</strong>, my assistant is ready.</p>
                <p>Return to Telegram and send <code>/start</code>.</p>
                <p style="color:#aaa;font-size:13px">You can close this tab.</p>
              </body>
            </html>
            """,
            status_code=200,
        )
    except Exception as exc:
        logger.error("OAuth callback failed: %s", exc, exc_info=True)
        return HTMLResponse(
            content=f"""
            <html>
              <body style="font-family:sans-serif;text-align:center;padding:60px">
                <h2>⚠️ Authentication Failed</h2>
                <p>Error: {str(exc)[:200]}</p>
                <p>Please try again via Telegram /start.</p>
              </body>
            </html>
            """,
            status_code=400,
        )
