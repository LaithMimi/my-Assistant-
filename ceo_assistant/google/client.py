"""
Builds authenticated Google API service clients for a given Telegram chat_id.
All clients auto-refresh tokens on expiry via the auth module.
"""

from __future__ import annotations

from googleapiclient.discovery import build  # type: ignore

from ceo_assistant.google.auth import get_credentials


def _service(chat_id: int, api: str, version: str):
    creds = get_credentials(chat_id)
    if creds is None:
        raise RuntimeError(
            f"chat_id {chat_id} is not authorised. Please run /start and complete Google OAuth."
        )
    return build(api, version, credentials=creds)


def get_gmail_service(chat_id: int):
    """Return an authorised Gmail API v1 client."""
    return _service(chat_id, "gmail", "v1")


def get_calendar_service(chat_id: int):
    """Return an authorised Google Calendar API v3 client."""
    return _service(chat_id, "calendar", "v3")


def get_tasks_service(chat_id: int):
    """Return an authorised Google Tasks API v1 client."""
    return _service(chat_id, "tasks", "v1")


def get_docs_service(chat_id: int):
    """Return an authorised Google Docs API v1 client."""
    return _service(chat_id, "docs", "v1")


def get_drive_service(chat_id: int):
    """Return an authorised Google Drive API v3 client."""
    return _service(chat_id, "drive", "v3")
