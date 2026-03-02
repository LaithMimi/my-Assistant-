"""
Telegram HTML formatting helpers.

Telegram HTML parse mode supports: <b>, <i>, <u>, <s>, <code>, <pre>, <a href>.
All user-supplied strings must be escaped before embedding in HTML.
"""

from __future__ import annotations

import html
from typing import Any


def escape_html(text: str) -> str:
    """Escape a plain-text string for safe inclusion in Telegram HTML messages."""
    return html.escape(str(text), quote=False)


def bold(text: str) -> str:
    return f"<b>{escape_html(text)}</b>"


def italic(text: str) -> str:
    return f"<i>{escape_html(text)}</i>"


def code(text: str) -> str:
    return f"<code>{escape_html(text)}</code>"


def link(label: str, url: str) -> str:
    return f'<a href="{url}">{escape_html(label)}</a>'


def bullet_list(items: list[str]) -> str:
    """Join a list of items as HTML bullet lines."""
    return "\n".join(f"• {item}" for item in items)


def format_email_list(emails: list[dict[str, Any]]) -> str:
    """
    Render the email triage result as an HTML-formatted Telegram message.

    Each email dict must have: priority_emoji, sender, subject, summary.
    """
    if not emails:
        return "📭 <b>Inbox is empty</b> — no unread emails."

    lines = [f"📧 <b>Email Triage</b> ({len(emails)} unread)\n"]
    for email in emails:
        emoji = email.get("priority_emoji", "⬜")
        sender = escape_html(email.get("sender", "Unknown"))
        subject = escape_html(email.get("subject", "(no subject)"))
        summary = escape_html(email.get("summary", ""))
        lines.append(f"{emoji} <b>{sender}</b> — {subject}\n   <i>{summary}</i>\n")
    return "\n".join(lines)


def format_task_list(tasks: list[dict[str, Any]]) -> str:
    """Render Google Tasks as an HTML-formatted list."""
    if not tasks:
        return "📋 <b>No open tasks</b> — you're all caught up! ✅"

    lines = [f"📋 <b>Tasks</b> ({len(tasks)})\n"]
    for task in tasks:
        status = "✅" if task.get("status") == "completed" else "🔲"
        title = escape_html(task.get("title", "Untitled"))
        due = task.get("due", "")
        notes = task.get("notes", "")
        line = f"{status} {title}"
        if due:
            line += f" | 📅 {escape_html(due)}"
        if notes:
            line += f"\n   <i>{escape_html(notes[:80])}</i>"
        lines.append(line)
    return "\n".join(lines)


def format_calendar_events(events: list[dict[str, Any]]) -> str:
    """Render calendar events as an HTML-formatted schedule."""
    if not events:
        return "📅 <b>No upcoming events</b> — calendar is clear."

    lines = [f"📅 <b>Upcoming Schedule</b>\n"]
    current_date = None
    for event in events:
        date_str = event.get("date", "")
        if date_str != current_date:
            lines.append(f"\n<b>{escape_html(date_str)}</b>")
            current_date = date_str
        time_range = escape_html(event.get("time_range", "All day"))
        title = escape_html(event.get("title", "Busy"))
        attendees = event.get("attendees", [])
        line = f"  • {time_range} — {title}"
        if attendees:
            att_str = ", ".join(escape_html(a) for a in attendees[:3])
            if len(attendees) > 3:
                att_str += f" +{len(attendees) - 3}"
            line += f"\n    👥 {att_str}"
        lines.append(line)
    return "\n".join(lines)
