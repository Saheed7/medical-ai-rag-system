"""Split documents into embedding-sized, overlapping chunks."""

from __future__ import annotations

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.config import settings
from app.core.exceptions import DocumentIngestionError
from app.core.logger import get_logger

logger = get_logger(__name__)


def build_splitter() -> RecursiveCharacterTextSplitter:
    """Splitter tuned for prose-heavy reference material.

    Separators are ordered most- to least-semantic so the splitter breaks on
    paragraphs before it resorts to slicing mid-word.
    """
    return RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        separators=["\n\n", "\n", ". ", "? ", "! ", "; ", ", ", " ", ""],
        length_function=len,
        keep_separator=True,
    )


def chunk_documents(documents: list[Document]) -> list[Document]:
    """Split pages into chunks and attach a stable chunk id to each."""
    if not documents:
        raise DocumentIngestionError("chunk_documents() received an empty document list.")

    chunks = build_splitter().split_documents(documents)

    # Drop fragments too short to carry meaning (headers, stray captions).
    chunks = [c for c in chunks if len(c.page_content.strip()) >= settings.min_chunk_chars]

    if not chunks:
        raise DocumentIngestionError("Chunking produced no usable chunks.")

    for index, chunk in enumerate(chunks):
        chunk.metadata["chunk_id"] = index

    avg = sum(len(c.page_content) for c in chunks) / len(chunks)
    logger.info(
        "Produced %d chunks (avg %.0f chars, size=%d, overlap=%d)",
        len(chunks), avg, settings.chunk_size, settings.chunk_overlap,
    )
    return chunks
