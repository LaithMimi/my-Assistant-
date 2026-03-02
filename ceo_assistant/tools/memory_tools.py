"""
Memory tools: save notes to Google Docs and semantic search via FAISS.
"""

from __future__ import annotations

import logging

from langchain_core.tools import tool

from ceo_assistant.memory import get_memory_manager

logger = logging.getLogger(__name__)

VALID_CATEGORIES = {"preference", "decision", "stakeholder", "note"}


def make_memory_tools(chat_id: int, ceo_name: str = "CEO"):
    @tool
    def memory_save(content: str, category: str = "note") -> str:
        """Save a note, preference, decision, or stakeholder detail to CEO's Google Doc memory.
        Args: content (str), category — preference|decision|stakeholder|note.
        Appends a structured entry to the Google Doc, then re-indexes FAISS."""
        cat = category.lower().strip()
        if cat not in VALID_CATEGORIES:
            cat = "note"
        try:
            mgr = get_memory_manager(chat_id, ceo_name)
            mgr.append_to_doc(content, cat)
            return f"🧠 <b>Memory saved</b> [{cat}]\n<i>{content[:120]}</i>"
        except Exception as exc:
            logger.error("memory_save failed for chat_id=%s: %s", chat_id, exc)
            return f"⚠️ Failed to save memory: {exc}"

    @tool
    def memory_search(query: str, k: int = 3) -> str:
        """Semantic search over CEO's Google Docs memory using FAISS.
        Args: query (str), k (int) — number of results (default: 3).
        Returns: top-k relevant memory chunks."""
        try:
            mgr = get_memory_manager(chat_id, ceo_name)
            chunks = mgr.search(query, k=k)
            if not chunks:
                return "🧠 <b>No relevant memories found</b> for that query."
            lines = [f"🧠 <b>Memory Recall</b> — top {len(chunks)} results\n"]
            for i, chunk in enumerate(chunks, 1):
                lines.append(f"<b>{i}.</b> {chunk[:300]}")
            return "\n\n".join(lines)
        except Exception as exc:
            logger.error("memory_search failed for chat_id=%s: %s", chat_id, exc)
            return f"⚠️ Memory search failed: {exc}"

    return memory_save, memory_search
