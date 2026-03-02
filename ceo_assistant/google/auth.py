"""
Google OAuth 2.0 flow for Telegram-based authentication.

Flow:
  1. /start in Telegram → bot sends https://BASE_URL/auth?chat_id=XXX
  2. User opens link → redirected to Google OAuth consent
  3. Google redirects to /auth/callback?code=...&state=chat_id
  4. Token stored as credentials/{chat_id}.json
  5. Bot sends confirmation message via Telegram
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

logger = logging.getLogger(__name__)

# All Google API scopes required
SCOPES: list[str] = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/tasks",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/userinfo.profile",
    "openid",
]

CREDENTIALS_DIR = Path("credentials")
CREDENTIALS_DIR.mkdir(exist_ok=True)


def _token_path(chat_id: int) -> Path:
    return CREDENTIALS_DIR / f"{chat_id}.json"


def _client_config() -> dict:
    """Build the OAuth client config dict from environment variables."""
    client_id = os.environ["GOOGLE_CLIENT_ID"].strip()
    client_secret = os.environ["GOOGLE_CLIENT_SECRET"].strip()
    redirect_uri = os.environ["GOOGLE_REDIRECT_URI"].strip()
    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uris": [redirect_uri],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }


def build_auth_url(chat_id: int) -> str:
    """Return the Google OAuth consent URL for a particular Telegram chat_id."""
    redirect_uri = os.environ["GOOGLE_REDIRECT_URI"]
    flow = Flow.from_client_config(
        _client_config(),
        scopes=SCOPES,
        redirect_uri=redirect_uri,
    )
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=str(chat_id),
    )
    return auth_url


def exchange_code(code: str, chat_id: int) -> Credentials:
    """Exchange the OAuth auth code for credentials and persist them."""
    redirect_uri = os.environ["GOOGLE_REDIRECT_URI"]
    flow = Flow.from_client_config(
        _client_config(),
        scopes=SCOPES,
        redirect_uri=redirect_uri,
    )
    flow.fetch_token(code=code)
    creds = flow.credentials
    _save_credentials(chat_id, creds)
    logger.info("OAuth tokens saved for chat_id=%s", chat_id)
    return creds


def get_credentials(chat_id: int) -> Optional[Credentials]:
    """
    Load credentials for a chat_id. Returns None if not yet authorised.
    Auto-refreshes if the token is expired.
    """
    token_path = _token_path(chat_id)
    if not token_path.exists():
        return None

    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_credentials(chat_id, creds)
            logger.info("Token refreshed for chat_id=%s", chat_id)
        except Exception as exc:
            logger.error("Token refresh failed for chat_id=%s: %s", chat_id, exc)
            return None

    return creds if creds.valid else None


def is_authorised(chat_id: int) -> bool:
    """Return True if the chat_id has valid Google credentials."""
    return get_credentials(chat_id) is not None


def _save_credentials(chat_id: int, creds: Credentials) -> None:
    token_path = _token_path(chat_id)
    token_data = json.loads(creds.to_json())
    # Persist the scopes so from_authorized_user_file can reload them
    token_data["scopes"] = SCOPES
    token_path.write_text(json.dumps(token_data, indent=2))


def get_user_name(chat_id: int) -> str:
    """Fetch the display name from the Google userinfo endpoint."""
    from googleapiclient.discovery import build  # type: ignore

    creds = get_credentials(chat_id)
    if not creds:
        return "CEO"
    try:
        service = build("oauth2", "v2", credentials=creds)
        info = service.userinfo().get().execute()
        return info.get("name", "CEO")
    except Exception:
        return "CEO"
