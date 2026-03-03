"""
LangGraph StateGraph Agent — v2 (Google AI Best Practices)

Changes from v1:
  - Memory is ON-DEMAND: no automatic memory_node before every call.
    The agent decides when to call memory_search based on context.
  - Every agent run is logged via eval_logger (tool calls + total latency).
  - Input sanitization applied before graph invocation.
  - LangSmith tracing wraps every invocation.

Flow:
  START → agent_node → (tool_node if tool call) → agent_node → END
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import date
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from ceo_assistant.prompts.system import build_system_prompt
from ceo_assistant.tools.calendar import make_calendar_tools
from ceo_assistant.tools.gmail import make_gmail_tools
from ceo_assistant.tools.meeting_brief import make_meeting_brief_tool
from ceo_assistant.tools.memory_tools import make_memory_tools
from ceo_assistant.tools.research import make_research_tools
from ceo_assistant.tools.tasks import make_tasks_tools
from ceo_assistant.utils.eval_logger import log_agent_run
from ceo_assistant.utils.sanitizer import sanitize_input

logger = logging.getLogger(__name__)


# ── State definition ──────────────────────────────────────────────────────

class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    chat_id: int
    ceo_profile: dict


# ── Tool registry (grouped by sub-agent domain for multi-agent readiness) ─

class ToolGroups:
    """
    Tools grouped by logical sub-agent domain.
    Designed so each group can be delegated to a specialised sub-agent later.

      EmailAgent    → gmail_triage, gmail_draft
      CalendarAgent → calendar_view, calendar_schedule, calendar_protect
      TaskAgent     → tasks_list, tasks_create, tasks_complete
      ResearchAgent → web_research
      MemoryAgent   → memory_save, memory_search, meeting_brief
    """
    def __init__(self, chat_id: int, ceo_name: str) -> None:
        self.chat_id = chat_id
        self.email = list(make_gmail_tools(chat_id))
        self.calendar = list(make_calendar_tools(chat_id))
        self.tasks = list(make_tasks_tools(chat_id))
        self.research = list(make_research_tools())
        self.memory = list(make_memory_tools(chat_id, ceo_name)) + list(
            make_meeting_brief_tool(chat_id, ceo_name)
        )

    @property
    def all(self) -> list:
        return self.email + self.calendar + self.tasks + self.research + self.memory


# ── Agent builder ─────────────────────────────────────────────────────────

def build_agent(chat_id: int, ceo_profile: dict):
    """
    Build and compile the LangGraph StateGraph for a CEO session.
    Memory is on-demand (no automatic pre-call injection).
    """
    ceo_name = ceo_profile.get("name", "CEO")
    groups = ToolGroups(chat_id, ceo_name)
    all_tools = groups.all

    llm = ChatOpenAI(model="gpt-4o", temperature=0.2, streaming=False).bind_tools(
        all_tools
    )
    tool_node = ToolNode(all_tools)

    def agent_node(state: AgentState) -> AgentState:
        system_content = build_system_prompt(
            ceo_profile=state["ceo_profile"],
            memory_context="",   # on-demand: agent calls memory_search explicitly
            today=date.today(),
        )
        messages_with_sys: list[BaseMessage] = [
            SystemMessage(content=system_content),
            *state["messages"],
        ]
        response = llm.invoke(messages_with_sys)
        return {**state, "messages": [response]}

    def should_continue(state: AgentState) -> str:
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and last.tool_calls:
            return "tool_node"
        return END

    graph = StateGraph(AgentState)
    graph.add_node("agent_node", agent_node)
    graph.add_node("tool_node", tool_node)

    graph.add_edge(START, "agent_node")
    graph.add_conditional_edges(
        "agent_node",
        should_continue,
        {"tool_node": "tool_node", END: END},
    )
    graph.add_edge("tool_node", "agent_node")

    import sqlite3
    from langgraph.checkpoint.sqlite import SqliteSaver
    from ceo_assistant.google.auth import DATA_DIR
    
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _memory_db_path = str(DATA_DIR / "chat_memory.sqlite")
    
    # Needs to be a persistent connection outside of a context manager block
    conn = sqlite3.connect(_memory_db_path, check_same_thread=False)
    memory_saver = SqliteSaver(conn)

    return graph.compile(checkpointer=memory_saver)


# ── Per-session cache ─────────────────────────────────────────────────────

_compiled_agents: dict[int, object] = {}


def get_agent(chat_id: int, ceo_profile: dict):
    if chat_id not in _compiled_agents:
        _compiled_agents[chat_id] = build_agent(chat_id, ceo_profile)
    return _compiled_agents[chat_id]


# ── Public run function ───────────────────────────────────────────────────

async def run_agent(chat_id: int, ceo_profile: dict, user_message: str) -> str:
    """
    Run the agent for a single CEO turn. Returns the assistant reply string.

    - Sanitizes user_message before processing
    - Wraps invocation with LangSmith tracing if API key is set
    - Logs the full run via eval_logger → Supabase
    """
    clean_message = sanitize_input(user_message)
    agent = get_agent(chat_id, ceo_profile)

    initial_state: AgentState = {
        "messages": [HumanMessage(content=clean_message)],
        "chat_id": chat_id,
        "ceo_profile": ceo_profile,
    }

    # LangSmith & checkpointer config
    config: dict = {"configurable": {"thread_id": str(chat_id)}}
    if os.environ.get("LANGSMITH_API_KEY"):
        project = os.environ.get("LANGSMITH_PROJECT", "ceo-assistant")
        config["run_name"] = f"ceo-agent-{chat_id}"
        config["tags"] = [f"chat_id:{chat_id}"]
        config["metadata"] = {"chat_id": str(chat_id), "project": project}

    t0 = time.monotonic()
    success = True
    error: str | None = None
    result_text = "✅ Done."
    tools_used: list[str] = []

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: agent.invoke(initial_state, config=config)
        )

        # Collect tools used from message history
        for msg in result["messages"]:
            if isinstance(msg, AIMessage) and msg.tool_calls:
                tools_used.extend(tc["name"] for tc in msg.tool_calls)

        # Extract final AI reply
        for msg in reversed(result["messages"]):
            if isinstance(msg, AIMessage) and not msg.tool_calls:
                result_text = msg.content or "✅ Done."
                break

    except Exception as exc:
        logger.error("Agent error for chat_id=%s: %s", chat_id, exc, exc_info=True)
        success = False
        error = str(exc)
        result_text = (
            f"⚠️ <b>Something went wrong.</b>\n"
            f"<code>{str(exc)[:200]}</code>\n\n"
            f"Please try again or rephrase your request."
        )

    latency_ms = (time.monotonic() - t0) * 1000

    # Fire-and-forget eval log
    asyncio.ensure_future(
        log_agent_run(
            chat_id=chat_id,
            user_input=clean_message,
            final_output=result_text,
            tools_used=list(dict.fromkeys(tools_used)),  # deduplicated, ordered
            total_latency_ms=latency_ms,
            success=success,
            error=error,
        )
    )

    return result_text
