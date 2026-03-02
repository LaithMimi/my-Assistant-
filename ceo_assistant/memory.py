"""
Google Docs-backed RAG memory system with FAISS local vector index.

Architecture:
  - One master Google Doc per CEO: "CEO Memory — {name}"
  - Doc has structured sections: ## Preferences, ## Decisions, ## Stakeholders, ## Notes
  - FAISS index stored locally at faiss_index/{chat_id}/
  - Index rebuilt on /start and after every memory_save call
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings

from ceo_assistant.google.client import get_docs_service, get_drive_service

logger = logging.getLogger(__name__)

FAISS_BASE = Path("faiss_index")
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50
DOC_TITLE_PREFIX = "CEO Memory"

SECTION_HEADERS = {
    "preference": "## Preferences",
    "decision": "## Decisions",
    "stakeholder": "## Stakeholders",
    "note": "## Notes & Learnings",
}


def _embeddings() -> OpenAIEmbeddings:
    return OpenAIEmbeddings(model="text-embedding-3-small")


class MemoryManager:
    """Per-CEO FAISS + Google Docs memory manager."""

    def __init__(self, chat_id: int, ceo_name: str = "CEO") -> None:
        self.chat_id = chat_id
        self.ceo_name = ceo_name
        self._index_path = FAISS_BASE / str(chat_id)
        self._index_path.mkdir(parents=True, exist_ok=True)
        self._doc_id: Optional[str] = None  # cached Google Doc ID

    # ── Google Doc management ────────────────────────────────────────────

    def _get_or_create_doc(self) -> str:
        """Find or create the CEO Memory Google Doc and return its ID."""
        if self._doc_id:
            return self._doc_id

        drive = get_drive_service(self.chat_id)
        title = f"{DOC_TITLE_PREFIX} — {self.ceo_name}"
        query = f"name='{title}' and mimeType='application/vnd.google-apps.document' and trashed=false"
        results = drive.files().list(q=query, fields="files(id, name)").execute()
        files = results.get("files", [])

        if files:
            self._doc_id = files[0]["id"]
            logger.info("Found existing memory doc: %s", self._doc_id)
            return self._doc_id

        # Create a new document
        docs_service = get_docs_service(self.chat_id)
        doc = docs_service.documents().create(body={"title": title}).execute()
        self._doc_id = doc["documentId"]
        logger.info("Created new memory doc: %s", self._doc_id)

        # Seed with section headers
        initial_content = "\n\n".join(SECTION_HEADERS.values())
        requests = [
            {
                "insertText": {
                    "location": {"index": 1},
                    "text": initial_content + "\n",
                }
            }
        ]
        docs_service.documents().batchUpdate(
            documentId=self._doc_id, body={"requests": requests}
        ).execute()
        return self._doc_id

    def _fetch_doc_text(self) -> str:
        """Return the full plain-text content of the CEO Memory doc."""
        doc_id = self._get_or_create_doc()
        docs_service = get_docs_service(self.chat_id)
        doc = docs_service.documents().get(documentId=doc_id).execute()
        lines: list[str] = []
        for element in doc.get("body", {}).get("content", []):
            para = element.get("paragraph")
            if para:
                for run in para.get("elements", []):
                    text_run = run.get("textRun")
                    if text_run:
                        lines.append(text_run.get("content", ""))
        return "".join(lines)

    # ── FAISS index management ────────────────────────────────────────────

    def build_index(self) -> None:
        """
        Fetch the Google Doc, split into chunks, embed, and save FAISS index.
        Call on /start and after every memory_save.
        """
        try:
            text = self._fetch_doc_text()
            if not text.strip():
                logger.info("Memory doc is empty; skipping index build for chat_id=%s", self.chat_id)
                return

            splitter = RecursiveCharacterTextSplitter(
                chunk_size=CHUNK_SIZE,
                chunk_overlap=CHUNK_OVERLAP,
                separators=["\n\n", "\n", " ", ""],
            )
            chunks = splitter.split_text(text)
            if not chunks:
                return

            embedder = _embeddings()
            index = FAISS.from_texts(chunks, embedder)
            index.save_local(str(self._index_path))
            logger.info(
                "FAISS index built: %d chunks for chat_id=%s", len(chunks), self.chat_id
            )
        except Exception as exc:
            logger.error("Failed to build FAISS index for chat_id=%s: %s", self.chat_id, exc)

    def search(self, query: str, k: int = 3) -> list[str]:
        """
        Run semantic similarity search over the local FAISS index.
        Returns up to k relevant text chunks.
        """
        index_file = self._index_path / "index.faiss"
        if not index_file.exists():
            logger.debug("No FAISS index yet for chat_id=%s", self.chat_id)
            return []

        try:
            embedder = _embeddings()
            index = FAISS.load_local(
                str(self._index_path),
                embedder,
                allow_dangerous_deserialization=True,
            )
            results = index.similarity_search(query, k=k)
            return [doc.page_content for doc in results]
        except Exception as exc:
            logger.error("FAISS search failed for chat_id=%s: %s", self.chat_id, exc)
            return []

    # ── Write operations ─────────────────────────────────────────────────

    def append_to_doc(self, content: str, category: str) -> None:
        """
        Append a structured memory entry to the Google Doc under the
        appropriate section, then rebuild the FAISS index.

        Args:
            content: The note/decision/preference text to save.
            category: One of preference | decision | stakeholder | note
        """
        doc_id = self._get_or_create_doc()
        docs_service = get_docs_service(self.chat_id)

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        entry = f"\n[{timestamp}] {content.strip()}"

        # Find the section header then insert after it
        section_header = SECTION_HEADERS.get(category, SECTION_HEADERS["note"])
        doc = docs_service.documents().get(documentId=doc_id).execute()

        # Locate the end index of the target section header
        insert_index = None
        body_content = doc.get("body", {}).get("content", [])
        for element in body_content:
            para = element.get("paragraph")
            if para:
                text = "".join(
                    run.get("textRun", {}).get("content", "")
                    for run in para.get("elements", [])
                ).strip()
                if text == section_header.strip():
                    end_index = element.get("endIndex", 1)
                    insert_index = end_index - 1  # before the trailing \n
                    break

        if insert_index is None:
            # Section not found → append at end of doc
            last = body_content[-1] if body_content else {}
            insert_index = last.get("endIndex", 1) - 1

        requests = [
            {
                "insertText": {
                    "location": {"index": insert_index},
                    "text": entry,
                }
            }
        ]
        docs_service.documents().batchUpdate(
            documentId=doc_id, body={"requests": requests}
        ).execute()
        logger.info("Memory appended to section '%s' for chat_id=%s", category, self.chat_id)

        # Rebuild index to include the new entry
        self.build_index()


# ── Module-level helpers used by tools ─────────────────────────────────────

_managers: dict[int, MemoryManager] = {}


def get_memory_manager(chat_id: int, ceo_name: str = "CEO") -> MemoryManager:
    """Return (or create) the MemoryManager singleton for a chat_id."""
    if chat_id not in _managers:
        _managers[chat_id] = MemoryManager(chat_id, ceo_name)
    return _managers[chat_id]
