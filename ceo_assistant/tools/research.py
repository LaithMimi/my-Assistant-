"""
Web research tool using the Tavily API.
"""

from __future__ import annotations

import logging
import os

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


def web_research_impl(query: str) -> str:
    """
    Search the web via Tavily and return a 5-bullet summary with source links.
    """
    try:
        from tavily import TavilyClient  # type: ignore

        client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
        response = client.search(
            query=query,
            search_depth="advanced",
            max_results=5,
            include_answer=True,
        )

        bullets: list[str] = []
        answer = response.get("answer", "")
        results = response.get("results", [])

        if answer:
            bullets.append(f"💡 <b>Summary:</b> {answer}")

        for r in results[:5]:
            title = r.get("title", "Source")
            url = r.get("url", "")
            content = r.get("content", "")[:150].replace("\n", " ")
            if url:
                bullets.append(f"• <a href=\"{url}\">{title}</a> — {content}…")
            else:
                bullets.append(f"• {title} — {content}…")

        return "\n".join(bullets) if bullets else "No results found."
    except Exception as exc:
        logger.error("web_research_impl failed for query '%s': %s", query, exc)
        return f"⚠️ Search failed: {exc}"


def make_research_tools():
    """Return the web_research @tool."""

    @tool
    def web_research(query: str) -> str:
        """Search the web and summarize findings.
        Args: query (str) — the search topic.
        Returns: 5-bullet summary with source links using Tavily API."""
        return web_research_impl(query)

    return (web_research,)
