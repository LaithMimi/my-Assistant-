"""
Gmail tools: triage inbox + draft emails.
"""

from __future__ import annotations

import base64
import logging
from email.mime.text import MIMEText
from typing import Any

from langchain_core.tools import tool
from openai import OpenAI

from ceo_assistant.google.client import get_gmail_service

logger = logging.getLogger(__name__)
_openai = OpenAI()


def _decode_payload(payload: dict) -> str:
    """Recursively extract plain-text body from a Gmail message payload."""
    mime = payload.get("mimeType", "")
    if mime == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
    elif mime.startswith("multipart/"):
        for part in payload.get("parts", []):
            text = _decode_payload(part)
            if text:
                return text
    return ""


def _header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def _classify_priority(sender: str, subject: str, snippet: str) -> tuple[str, str]:
    """Use GPT-4o to classify email priority. Returns (emoji, label)."""
    prompt = (
        f"Classify this email priority. Reply with ONLY one word: URGENT, ACTION, FYI, or ARCHIVE.\n"
        f"From: {sender}\nSubject: {subject}\nSnippet: {snippet}"
    )
    try:
        resp = _openai.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=10,
            temperature=0,
        )
        label = resp.choices[0].message.content.strip().upper()
    except Exception:
        label = "FYI"
    mapping = {
        "URGENT": ("🔴", "Urgent"),
        "ACTION": ("🟡", "Action needed"),
        "FYI": ("🔵", "FYI"),
        "ARCHIVE": ("⬜", "Archive"),
    }
    return mapping.get(label, ("🔵", "FYI"))


def _one_line_summary(snippet: str) -> str:
    """Produce a 1-line summary from the email snippet using GPT-4o mini."""
    if not snippet:
        return ""
    try:
        resp = _openai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "user",
                    "content": f"Summarise this email in max 15 words:\n{snippet}",
                }
            ],
            max_tokens=30,
            temperature=0,
        )
        return resp.choices[0].message.content.strip()
    except Exception:
        return snippet[:100]


def gmail_triage_impl(chat_id: int) -> list[dict[str, Any]]:
    """
    Fetch the last 20 unread emails, classify by priority, and return
    a list of dicts: priority_emoji, sender, subject, summary.
    """
    service = get_gmail_service(chat_id)
    result = (
        service.users()
        .messages()
        .list(userId="me", q="is:unread", maxResults=20)
        .execute()
    )
    messages = result.get("messages", [])
    if not messages:
        return []

    emails: list[dict[str, Any]] = []
    for msg_meta in messages:
        try:
            msg = (
                service.users()
                .messages()
                .get(userId="me", id=msg_meta["id"], format="full")
                .execute()
            )
            headers = msg.get("payload", {}).get("headers", [])
            sender = _header(headers, "From")
            subject = _header(headers, "Subject") or "(no subject)"
            snippet = msg.get("snippet", "")
            emoji, _ = _classify_priority(sender, subject, snippet)
            summary = _one_line_summary(snippet)
            emails.append(
                {
                    "priority_emoji": emoji,
                    "sender": sender,
                    "subject": subject,
                    "summary": summary,
                    "message_id": msg_meta["id"],
                }
            )
        except Exception as exc:
            logger.warning("Failed to process email %s: %s", msg_meta["id"], exc)
    return emails


def gmail_draft_impl(
    chat_id: int,
    recipient: str,
    context: str,
    tone: str,
    key_message: str,
) -> dict[str, str]:
    """
    Draft an email in the CEO's voice.
    Returns dict with 'subject' and 'body'.
    """
    prompt = (
        f"You are drafting an email on behalf of a CEO.\n"
        f"Recipient: {recipient}\n"
        f"Context: {context}\n"
        f"Tone: {tone}\n"
        f"Key message: {key_message}\n\n"
        f"Write a professional email with Subject and Body separated by '---BODY---'. "
        f"Subject line first, then '---BODY---', then the body. No extra commentary."
    )
    try:
        resp = _openai.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500,
            temperature=0.4,
        )
        text = resp.choices[0].message.content.strip()
        if "---BODY---" in text:
            parts = text.split("---BODY---", 1)
            subject = parts[0].replace("Subject:", "").strip()
            body = parts[1].strip()
        else:
            lines = text.splitlines()
            subject = lines[0].replace("Subject:", "").strip()
            body = "\n".join(lines[1:]).strip()
        return {"subject": subject, "body": body}
    except Exception as exc:
        logger.error("gmail_draft_impl failed: %s", exc)
        return {"subject": "Draft email", "body": key_message}


def gmail_send_impl(chat_id: int, recipient: str, subject: str, body: str) -> str:
    """Send an email using Gmail API."""
    try:
        service = get_gmail_service(chat_id)
        message = MIMEText(body)
        message["to"] = recipient
        message["subject"] = subject
        raw_msg = base64.urlsafe_b64encode(message.as_bytes()).decode()
        sent = (
            service.users()
            .messages()
            .send(userId="me", body={"raw": raw_msg})
            .execute()
        )
        return f"Email sent successfully to {recipient} (ID: {sent['id']})."
    except Exception as exc:
        logger.error("Failed to send email to %s: %s", recipient, exc)
        return f"Failed to send email: {exc}"


# ── LangChain @tool wrappers ──────────────────────────────────────────────

def make_gmail_tools(chat_id: int):
    """Return bound @tool functions for the given chat_id."""

    @tool
    def gmail_triage() -> str:
        """Fetch last 20 unread emails, classify by priority.
        Returns structured list: emoji + sender + subject + 1-line summary.
        Priority: 🔴 urgent / 🟡 action needed / 🔵 FYI / ⬜ archive"""
        emails = gmail_triage_impl(chat_id)
        if not emails:
            return "📭 No unread emails — inbox is clear."
        lines = [f"📧 <b>Email Triage</b> — {len(emails)} unread\n"]
        for e in emails:
            lines.append(
                f"{e['priority_emoji']} <b>{e['sender']}</b> — {e['subject']}\n"
                f"   <i>{e['summary']}</i>"
            )
        return "\n\n".join(lines)

    @tool
    def gmail_draft(recipient: str, context: str, tone: str, key_message: str) -> str:
        """Draft an email in the CEO's voice.
        Args: recipient, context, tone, key_message.
        Returns subject + body as a formatted Telegram message."""
        draft = gmail_draft_impl(chat_id, recipient, context, tone, key_message)
        return (
            f"📧 <b>Draft Email</b>\n\n"
            f"<b>To:</b> {recipient}\n"
            f"<b>Subject:</b> {draft['subject']}\n\n"
            f"{draft['body']}\n\n"
            f"<i>⚠️ Review before sending. Reply 'send' to dispatch via Gmail.</i>"
        )

    @tool
    def gmail_send(recipient: str, subject: str, body: str) -> str:
        """Actually send an email via Gmail API. 
        Args: recipient, subject, body.
        Only use this if the user has EXPLICITLY confirmed they want to send an existing draft."""
        from ceo_assistant.utils import confirmation
        
        # Must be async because confirmation.confirm() awaits it
        async def action():
            import asyncio
            # Offload blocking synchronous Gmail API call to thread pool to avoid blocking the bot loop
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                None, lambda: gmail_send_impl(chat_id, recipient, subject, body)
            )
            
        preview = f"<b>To:</b> {recipient}\n<b>Subject:</b> {subject}\n\n<i>{body[:150]}...</i>"
        
        return confirmation.register(
            chat_id=chat_id,
            label="Dispatch drafted email via Gmail",
            preview=preview,
            execute_fn=action
        )

    return gmail_triage, gmail_draft, gmail_send
