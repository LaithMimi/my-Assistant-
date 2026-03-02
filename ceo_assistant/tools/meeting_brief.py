"""
Meeting brief tool: generates a pre-meeting briefing for the next calendar event.
"""

from __future__ import annotations

import logging

from langchain_core.tools import tool
from openai import OpenAI

from ceo_assistant.google.client import get_gmail_service
from ceo_assistant.memory import get_memory_manager
from ceo_assistant.tools.calendar import calendar_view_impl

logger = logging.getLogger(__name__)
_openai = OpenAI()


def _search_related_emails(chat_id: int, event_title: str, attendees: list[str]) -> list[str]:
    """Search Gmail for threads related to the meeting."""
    service = get_gmail_service(chat_id)
    snippets: list[str] = []
    queries = []
    if event_title:
        queries.append(event_title[:50])
    for email in attendees[:3]:
        queries.append(f"from:{email}")

    for q in queries[:2]:  # limit API calls
        try:
            result = (
                service.users()
                .messages()
                .list(userId="me", q=q, maxResults=3)
                .execute()
            )
            for msg_meta in result.get("messages", [])[:3]:
                msg = (
                    service.users()
                    .messages()
                    .get(userId="me", id=msg_meta["id"], format="metadata",
                         metadataHeaders=["Subject", "From"])
                    .execute()
                )
                snippet = msg.get("snippet", "")
                if snippet:
                    snippets.append(snippet[:200])
        except Exception as exc:
            logger.warning("Email search failed for '%s': %s", q, exc)
    return snippets


def meeting_brief_impl(chat_id: int, ceo_name: str = "CEO") -> str:
    """Generate a briefing for the next calendar event."""
    events = calendar_view_impl(chat_id, days=2)
    if not events:
        return "📅 No upcoming meetings in the next 2 days."

    next_event = events[0]
    title = next_event["title"]
    time_range = next_event["time_range"]
    date = next_event["date"]
    attendees = next_event["attendees"]
    description = next_event.get("description", "")

    # Memory context
    mgr = get_memory_manager(chat_id, ceo_name)
    mem_chunks = mgr.search(title, k=3)
    mem_context = "\n".join(mem_chunks) if mem_chunks else "No prior notes found."

    # Email context
    email_snippets = _search_related_emails(chat_id, title, attendees)
    email_context = "\n".join(email_snippets[:5]) if email_snippets else "No recent email threads found."

    prompt = f"""Generate a pre-meeting briefing for this calendar event.

Event: {title}
Date/Time: {date} {time_range}
Attendees: {', '.join(attendees) if attendees else 'Not specified'}
Description: {description or 'None'}

Related email threads:
{email_context}

CEO memory context:
{mem_context}

Output EXACTLY in this format — use Telegram HTML:
<b>📋 Meeting Brief: {title}</b>

<b>📌 Context</b>
[2-3 sentences about the meeting purpose and attendees]

<b>📑 Agenda</b>
[Bullet list of likely agenda items]

<b>⚠️ Watch-outs</b>
[Any risks, open questions, or things to be careful about]

<b>💬 Talking Points</b>
[3-5 specific, actionable talking points for the CEO]"""

    try:
        resp = _openai.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=700,
            temperature=0.3,
        )
        return resp.choices[0].message.content.strip()
    except Exception as exc:
        logger.error("meeting_brief_impl failed: %s", exc)
        return f"⚠️ Could not generate briefing: {exc}"


def make_meeting_brief_tool(chat_id: int, ceo_name: str = "CEO"):
    @tool
    def meeting_brief() -> str:
        """Generate a pre-meeting briefing for the next calendar event.
        Fetches event details + related email thread + past notes from memory.
        Returns: Context / Agenda / Watch-outs / Talking points."""
        return meeting_brief_impl(chat_id, ceo_name)

    return (meeting_brief,)
