"""One-shot pipeline: PDFs -> cleaned pages -> chunks -> FAISS index.

Run with:  python -m app.ingestion.build_index
"""

from __future__ import annotations

import argparse
import time

from app.core.logger import get_logger
from app.ingestion.chunker import chunk_documents
from app.ingestion.pdf_loader import load_documents
from app.rag.vector_store import build_vector_store

logger = get_logger(__name__)


def run(force: bool = False) -> None:
    started = time.perf_counter()
    logger.info("=== Index build started ===")

    documents = load_documents()
    chunks = chunk_documents(documents)
    build_vector_store(chunks, force=force)

    logger.info("=== Index build finished in %.1fs ===", time.perf_counter() - started)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the FAISS vector index.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild even if an index already exists on disk.",
    )
    run(force=parser.parse_args().force)


if __name__ == "__main__":
    main()
