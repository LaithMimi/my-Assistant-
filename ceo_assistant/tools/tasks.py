"""
Google Tasks tools: list, create, complete tasks.

Confirmation protocol applied to tasks_create and tasks_complete:
  - These tools register a pending action and return a preview/confirmation prompt.
  - The CEO must reply 'yes' to execute (handled in bot.py).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from langchain_core.tools import tool

from ceo_assistant.google.client import get_tasks_service
from ceo_assistant.utils import confirmation as confirm_mgr
from ceo_assistant.utils.eval_logger import ToolTimer

logger = logging.getLogger(__name__)


def _format_due(due_str: Optional[str]) -> str:
    if not due_str:
        return ""
    try:
        dt = datetime.fromisoformat(due_str.replace("Z", "+00:00"))
        return dt.strftime("%b %d, %Y").replace(" 0", " ")
    except Exception:
        return due_str[:10]


def tasks_list_impl(chat_id: int, filter: str = "all") -> list[dict]:
    service = get_tasks_service(chat_id)
    tasklists = service.tasklists().list(maxResults=20).execute().get("items", [])
    tasks: list[dict] = []
    now = datetime.now(timezone.utc).date()

    for tl in tasklists:
        tl_id, tl_title = tl["id"], tl.get("title", "Tasks")
        items = (
            service.tasks()
            .list(tasklist=tl_id, showCompleted=False, maxResults=100)
            .execute()
            .get("items", [])
        )
        for item in items:
            due_str = item.get("due", "")
            due_date = None
            if due_str:
                try:
                    due_date = datetime.fromisoformat(due_str.replace("Z", "+00:00")).date()
                except Exception:
                    pass
            if filter == "today" and (due_date is None or due_date != now):
                continue
            if filter == "overdue" and (due_date is None or due_date >= now):
                continue
            tasks.append({
                "id": item.get("id", ""),
                "tasklist_id": tl_id,
                "tasklist": tl_title,
                "title": item.get("title", "Untitled"),
                "status": item.get("status", "needsAction"),
                "due": _format_due(due_str),
                "notes": item.get("notes", ""),
            })
    return tasks


def _do_tasks_create(chat_id: int, title: str, due_date: str, notes: str, tasklist: str) -> dict:
    service = get_tasks_service(chat_id)
    task_body: dict = {"title": title}
    if notes:
        task_body["notes"] = notes
    if due_date:
        try:
            dt = datetime.fromisoformat(f"{due_date}T00:00:00+00:00")
            task_body["due"] = dt.isoformat().replace("+00:00", "Z")
        except Exception:
            pass
    created = service.tasks().insert(tasklist=tasklist, body=task_body).execute()
    return {"id": created.get("id", ""), "title": created.get("title", title), "due": _format_due(created.get("due", ""))}


def _do_tasks_complete(chat_id: int, task_id: str, tasklist_id: str) -> bool:
    service = get_tasks_service(chat_id)
    try:
        service.tasks().patch(
            tasklist=tasklist_id, task=task_id, body={"status": "completed"}
        ).execute()
        return True
    except Exception as exc:
        logger.error("tasks_complete API call failed: %s", exc)
        return False


# ── LangChain @tool wrappers ──────────────────────────────────────────────

def make_tasks_tools(chat_id: int):

    @tool
    def tasks_list(filter: str = "all") -> str:
        """Fetch tasks from Google Tasks API.
        Args: filter — 'today' | 'overdue' | 'all' (default: 'all').
        Returns: formatted task list."""
        with ToolTimer(chat_id, "tasks_list", {"filter": filter}) as t:
            try:
                tasks = tasks_list_impl(chat_id, filter)
                if not tasks:
                    t.output = "empty"
                    return f"📋 <b>No tasks</b> ({filter}) — all clear! ✅"
                lines = [f"📋 <b>Tasks ({filter})</b> — {len(tasks)} items\n"]
                for task in tasks:
                    icon = "✅" if task["status"] == "completed" else "🔲"
                    line = f"{icon} {task['title']}"
                    if task["due"]:
                        line += f" | 📅 {task['due']}"
                    if task["notes"]:
                        line += f"\n   <i>{task['notes'][:80]}</i>"
                    lines.append(line)
                result = "\n".join(lines)
                t.output = f"{len(tasks)} tasks"
                return result
            except Exception as exc:
                t.output = str(exc)
                logger.error("tasks_list failed: %s", exc)
                return f"⚠️ Could not fetch tasks: {exc}"

    @tool
    def tasks_create(title: str, due_date: str = "", notes: str = "", tasklist: str = "@default") -> str:
        """Propose creating a new Google Task (requires CEO confirmation).
        Args: title, due_date (YYYY-MM-DD), notes, tasklist (default '@default').
        Returns: confirmation prompt — CEO must reply 'yes' to create."""
        with ToolTimer(chat_id, "tasks_create", {"title": title, "due_date": due_date}) as t:
            try:
                preview_lines = [f"📋 <b>{title}</b>"]
                if due_date:
                    preview_lines.append(f"📅 Due: {due_date}")
                if notes:
                    preview_lines.append(f"📝 {notes[:100]}")
                preview = "\n".join(preview_lines)

                async def _execute() -> str:
                    loop = asyncio.get_event_loop()
                    task = await loop.run_in_executor(
                        None, lambda: _do_tasks_create(chat_id, title, due_date, notes, tasklist)
                    )
                    msg = f"✅ <b>Task created:</b> {task['title']}"
                    if task["due"]:
                        msg += f"\n📅 Due: {task['due']}"
                    return msg

                prompt = confirm_mgr.register(chat_id, f"Create task: {title}", preview, _execute)
                t.output = "confirmation_requested"
                return prompt
            except Exception as exc:
                t.output = str(exc)
                logger.error("tasks_create failed: %s", exc)
                return f"⚠️ Could not prepare task: {exc}"

    @tool
    def tasks_complete(task_id: str, tasklist_id: str = "@default") -> str:
        """Propose marking a Google Task as complete (requires CEO confirmation).
        Args: task_id, tasklist_id (default '@default').
        Returns: confirmation prompt."""
        with ToolTimer(chat_id, "tasks_complete", {"task_id": task_id}) as t:
            try:
                preview = f"🔲 Mark task <code>{task_id}</code> as ✅ complete"

                async def _execute() -> str:
                    loop = asyncio.get_event_loop()
                    ok = await loop.run_in_executor(
                        None, lambda: _do_tasks_complete(chat_id, task_id, tasklist_id)
                    )
                    if ok:
                        return f"✅ Task <code>{task_id}</code> marked as complete!"
                    return f"⚠️ Could not complete task. Check the task ID and try again."

                prompt = confirm_mgr.register(chat_id, f"Complete task {task_id}", preview, _execute)
                t.output = "confirmation_requested"
                return prompt
            except Exception as exc:
                t.output = str(exc)
                logger.error("tasks_complete failed: %s", exc)
                return f"⚠️ Could not prepare completion: {exc}"

    return tasks_list, tasks_create, tasks_complete
