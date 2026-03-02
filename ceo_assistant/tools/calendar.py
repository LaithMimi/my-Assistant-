"""
Google Calendar tools: view events, schedule meetings, protect focus time.

Confirmation protocol applied to calendar_schedule and calendar_protect:
  - These tools register a pending action and return a preview confirmation.
  - The CEO must reply 'yes' to execute (handled in bot.py).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from langchain_core.tools import tool

from ceo_assistant.google.client import get_calendar_service
from ceo_assistant.utils import confirmation as confirm_mgr
from ceo_assistant.utils.eval_logger import ToolTimer

logger = logging.getLogger(__name__)


def _rfc3339(dt: datetime) -> str:
    return dt.isoformat()


def _parse_event(event: dict) -> dict:
    start_raw = event.get("start", {})
    end_raw = event.get("end", {})
    start_str = start_raw.get("dateTime", start_raw.get("date", ""))
    end_str = end_raw.get("dateTime", end_raw.get("date", ""))
    try:
        start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
        try:
            date_label = start_dt.strftime("%-d %b %Y, %A")
        except ValueError:
            date_label = start_dt.strftime("%d %b %Y, %A").lstrip("0")
        time_range = f"{start_dt.strftime('%H:%M')} – {end_dt.strftime('%H:%M')}"
    except Exception:
        date_label = start_str[:10]
        time_range = "All day"

    attendees = [a.get("email", "") for a in event.get("attendees", []) if a.get("email")]
    return {
        "id": event.get("id", ""),
        "title": event.get("summary", "Busy"),
        "date": date_label,
        "time_range": time_range,
        "start_iso": start_str,
        "attendees": attendees,
        "description": event.get("description", ""),
        "meet_link": event.get("hangoutLink", ""),
        "html_link": event.get("htmlLink", ""),
    }


def calendar_view_impl(chat_id: int, days: int = 1) -> list[dict]:
    service = get_calendar_service(chat_id)
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=days)
    result = service.events().list(
        calendarId="primary",
        timeMin=now.isoformat(),
        timeMax=end.isoformat(),
        singleEvents=True,
        orderBy="startTime",
        maxResults=20,
    ).execute()
    return [_parse_event(e) for e in result.get("items", [])]


def _do_calendar_schedule(
    chat_id: int,
    title: str,
    participants: list[str],
    duration_minutes: int,
    preferred_time: str,
    description: str,
) -> dict:
    """Execute the calendar event creation (called after confirmation)."""
    service = get_calendar_service(chat_id)
    try:
        if "T" in preferred_time:
            start_dt = datetime.fromisoformat(preferred_time.replace("Z", "+00:00"))
        else:
            start_dt = datetime.fromisoformat(preferred_time.replace(" ", "T") + ":00").replace(tzinfo=timezone.utc)
    except Exception:
        start_dt = datetime.now(timezone.utc) + timedelta(hours=1)

    end_dt = start_dt + timedelta(minutes=duration_minutes)
    event_body: dict = {
        "summary": title,
        "description": description,
        "start": {"dateTime": _rfc3339(start_dt), "timeZone": "UTC"},
        "end": {"dateTime": _rfc3339(end_dt), "timeZone": "UTC"},
        "conferenceData": {
            "createRequest": {"requestId": f"ceo-{title[:8]}", "conferenceSolutionKey": {"type": "hangoutsMeet"}}
        },
    }
    if participants:
        event_body["attendees"] = [{"email": p} for p in participants]
    created = service.events().insert(
        calendarId="primary", body=event_body, sendUpdates="all", conferenceDataVersion=1
    ).execute()
    return {
        "html_link": created.get("htmlLink", ""),
        "meet_link": created.get("hangoutLink", ""),
        "title": title,
        "start": _rfc3339(start_dt),
        "duration": duration_minutes,
        "participants": participants,
    }


def _do_calendar_protect(
    chat_id: int, date: str, start_time: str, duration_minutes: int, label: str
) -> dict:
    """Execute focus time blocking (called after confirmation)."""
    service = get_calendar_service(chat_id)
    try:
        start_dt = datetime.fromisoformat(f"{date}T{start_time}:00+00:00")
    except Exception:
        start_dt = datetime.now(timezone.utc)
    end_dt = start_dt + timedelta(minutes=duration_minutes)
    event_body = {
        "summary": label,
        "start": {"dateTime": _rfc3339(start_dt), "timeZone": "UTC"},
        "end": {"dateTime": _rfc3339(end_dt), "timeZone": "UTC"},
        "transparency": "opaque",
        "visibility": "private",
    }
    created = service.events().insert(calendarId="primary", body=event_body).execute()
    return {"html_link": created.get("htmlLink", ""), "label": label}


# ── LangChain @tool wrappers ──────────────────────────────────────────────

def make_calendar_tools(chat_id: int):

    @tool
    def calendar_view(days: int = 1) -> str:
        """Fetch upcoming calendar events.
        Args: days (int) — look-ahead in days (default 1).
        Returns: structured schedule with time, title, attendees."""
        with ToolTimer(chat_id, "calendar_view", {"days": days}) as t:
            try:
                events = calendar_view_impl(chat_id, days)
                if not events:
                    t.output = "empty"
                    return f"📅 <b>No events</b> in the next {days} day(s) — calendar is clear."
                lines = [f"📅 <b>Schedule — Next {days} Day(s)</b>\n"]
                current_date = None
                for ev in events:
                    if ev["date"] != current_date:
                        lines.append(f"\n<b>{ev['date']}</b>")
                        current_date = ev["date"]
                    line = f"  • {ev['time_range']} — {ev['title']}"
                    if ev["attendees"]:
                        line += f"\n    👥 {', '.join(ev['attendees'][:3])}"
                    if ev["meet_link"]:
                        line += f'\n    🎥 <a href="{ev["meet_link"]}">Google Meet</a>'
                    lines.append(line)
                result = "\n".join(lines)
                t.output = result
                return result
            except Exception as exc:
                t.output = str(exc)
                logger.error("calendar_view failed: %s", exc)
                return f"⚠️ Could not fetch calendar: {exc}"

    @tool
    def calendar_schedule(
        title: str,
        participants: list,
        duration_minutes: int,
        preferred_time: str,
        description: str = "",
    ) -> str:
        """Propose creating a Google Calendar event (requires CEO confirmation).
        Args: title, participants (emails), duration_minutes, preferred_time (ISO or 'YYYY-MM-DD HH:MM'), description.
        Returns: confirmation prompt — CEO must reply 'yes' to book."""
        with ToolTimer(chat_id, "calendar_schedule", {"title": title, "preferred_time": preferred_time}) as t:
            try:
                # Build human-readable preview
                preview_lines = [
                    f"📅 <b>{title}</b>",
                    f"🕐 {preferred_time} UTC ({duration_minutes} min)",
                ]
                if participants:
                    preview_lines.append(f"👥 Inviting: {', '.join(participants)}")
                if description:
                    preview_lines.append(f"📝 {description[:100]}")
                preview = "\n".join(preview_lines)

                # Register async callback
                async def _execute() -> str:
                    loop = asyncio.get_event_loop()
                    result = await loop.run_in_executor(
                        None,
                        lambda: _do_calendar_schedule(
                            chat_id, title, participants, duration_minutes, preferred_time, description
                        ),
                    )
                    lines = [
                        "✅ <b>Meeting booked!</b>",
                        f"📅 <b>{result['title']}</b>",
                        f"🕐 {result['start'][:16].replace('T', ' ')} UTC ({result['duration']} min)",
                    ]
                    if result.get("meet_link"):
                        lines.append(f'🎥 <a href="{result["meet_link"]}">Join Google Meet</a>')
                    lines.append(f'🔗 <a href="{result["html_link"]}">View in Calendar</a>')
                    return "\n".join(lines)

                prompt = confirm_mgr.register(chat_id, "Book calendar event", preview, _execute)
                t.output = "confirmation_requested"
                return prompt
            except Exception as exc:
                t.output = str(exc)
                logger.error("calendar_schedule failed: %s", exc)
                return f"⚠️ Could not prepare event: {exc}"

    @tool
    def calendar_protect(
        date: str, start_time: str, duration_minutes: int, label: str = "⚡ Focus Time"
    ) -> str:
        """Propose blocking focus time on the CEO's calendar (requires confirmation).
        Args: date (YYYY-MM-DD), start_time (HH:MM), duration_minutes, label.
        Returns: confirmation prompt."""
        with ToolTimer(chat_id, "calendar_protect", {"date": date, "start_time": start_time}) as t:
            try:
                preview = (
                    f"📅 {date} at {start_time} UTC ({duration_minutes} min)\n"
                    f"🏷️ Label: {label}"
                )

                async def _execute() -> str:
                    loop = asyncio.get_event_loop()
                    result = await loop.run_in_executor(
                        None,
                        lambda: _do_calendar_protect(chat_id, date, start_time, duration_minutes, label),
                    )
                    return (
                        f"🛡️ <b>Focus time blocked!</b>\n"
                        f"📅 {date} {start_time} UTC ({duration_minutes} min)\n"
                        f"🏷️ {label}\n"
                        f'🔗 <a href="{result["html_link"]}">View in Calendar</a>'
                    )

                prompt = confirm_mgr.register(chat_id, "Block focus time", preview, _execute)
                t.output = "confirmation_requested"
                return prompt
            except Exception as exc:
                t.output = str(exc)
                logger.error("calendar_protect failed: %s", exc)
                return f"⚠️ Could not prepare focus block: {exc}"

    return calendar_view, calendar_schedule, calendar_protect
