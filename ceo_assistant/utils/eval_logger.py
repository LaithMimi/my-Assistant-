"""
Evaluation & observability logger.

Per Google AI Agents Whitepaper — "Evaluation Hooks":
- Log every tool invocation: tool_name, input, output, latency, success
- Log every agent run: chat_id, user_input, final_output, total_latency
- Persist to Supabase `agent_logs` table for future fine-tuning / analytics
- Gracefully degrade if Supabase is unavailable (log to stderr only)

SQL schema (run once in Supabase SQL editor):
  See db/migrations.sql
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Optional

logger = logging.getLogger(__name__)

_supabase_client = None


def _get_supabase():
    """Lazily initialise the Supabase client."""
    global _supabase_client
    if _supabase_client is not None:
        return _supabase_client

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        return None

    try:
        from supabase import create_client  # type: ignore
        _supabase_client = create_client(url, key)
        return _supabase_client
    except ImportError:
        logger.warning("supabase package not installed — eval logging disabled.")
        return None
    except Exception as exc:
        logger.warning("Supabase connection failed: %s — eval logging disabled.", exc)
        return None


async def _insert_log(record: dict[str, Any]) -> None:
    """Insert a log record into Supabase agent_logs (non-blocking)."""
    client = _get_supabase()
    if client is None:
        return
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: client.table("agent_logs").insert(record).execute(),
        )
    except Exception as exc:
        logger.debug("Supabase insert failed (non-critical): %s", exc)


async def log_tool_call(
    chat_id: int,
    tool_name: str,
    tool_input: Any,
    tool_output: Any,
    latency_ms: float,
    success: bool,
    error: Optional[str] = None,
) -> None:
    """
    Log a single tool invocation.

    Args:
        chat_id:     Telegram chat ID (CEO session)
        tool_name:   Name of the tool that was invoked
        tool_input:  The arguments passed to the tool
        tool_output: The result returned by the tool (truncated to 500 chars)
        latency_ms:  Wall-clock execution time in milliseconds
        success:     False if the tool raised an exception
        error:       Exception message if success=False
    """
    record = {
        "event_type": "tool_call",
        "chat_id": str(chat_id),
        "tool_name": tool_name,
        "tool_input": str(tool_input)[:500],
        "tool_output": str(tool_output)[:500],
        "latency_ms": round(latency_ms, 2),
        "success": success,
        "error": error,
    }
    logger.info(
        "TOOL %s | chat=%s | %.0f ms | ok=%s",
        tool_name,
        chat_id,
        latency_ms,
        success,
    )
    await _insert_log(record)


async def log_agent_run(
    chat_id: int,
    user_input: str,
    final_output: str,
    tools_used: list[str],
    total_latency_ms: float,
    success: bool,
    error: Optional[str] = None,
) -> None:
    """
    Log a complete agent run (one user turn).
    """
    record = {
        "event_type": "agent_run",
        "chat_id": str(chat_id),
        "user_input": user_input[:300],
        "final_output": final_output[:500],
        "tools_used": tools_used,
        "latency_ms": round(total_latency_ms, 2),
        "success": success,
        "error": error,
    }
    logger.info(
        "AGENT RUN | chat=%s | tools=%s | %.0f ms | ok=%s",
        chat_id,
        tools_used,
        total_latency_ms,
        success,
    )
    await _insert_log(record)


class ToolTimer:
    """Context manager to measure tool latency and log the result."""

    def __init__(
        self, chat_id: int, tool_name: str, tool_input: Any
    ) -> None:
        self.chat_id = chat_id
        self.tool_name = tool_name
        self.tool_input = tool_input
        self._start: float = 0.0
        self.output: Any = None
        self.success: bool = True
        self.error: Optional[str] = None

    def __enter__(self) -> "ToolTimer":
        self._start = time.monotonic()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        latency = (time.monotonic() - self._start) * 1000
        if exc_type is not None:
            self.success = False
            self.error = str(exc_val)
        # Schedule async log without blocking
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(
                    log_tool_call(
                        self.chat_id,
                        self.tool_name,
                        self.tool_input,
                        self.output,
                        latency,
                        self.success,
                        self.error,
                    )
                )
        except Exception:
            pass
        return False  # don't suppress exceptions
