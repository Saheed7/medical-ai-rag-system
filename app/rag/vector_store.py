"""FAISS vector store lifecycle: build, save, load."""

from __future__ import annotations

import shutil
from pathlib import Path

from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document

from app.core.config import settings
from app.core.exceptions import VectorStoreError
from app.core.logger import get_logger
from app.rag.embeddings import get_embedding_model

logger = get_logger(__name__)


def index_exists(path: Path | None = None) -> bool:
    """True when a complete FAISS index is present on disk."""
    directory = Path(path or settings.vectorstore_dir)
    return (directory / "index.faiss").exists() and (directory / "index.pkl").exists()


def build_vector_store(chunks: list[Document], force: bool = False) -> FAISS:
    """Embed chunks and persist a FAISS index to disk."""
    if not chunks:
        raise VectorStoreError("Cannot build a vector store from zero chunks.")

    target = Path(settings.vectorstore_dir)

    if index_exists(target) and not force:
        logger.warning(
            "Index already exists at %s. Re-run with --force to rebuild.", target
        )
        return load_vector_store()

    if target.exists() and force:
        logger.info("Removing existing index at %s", target)
        shutil.rmtree(target)

    try:
        logger.info("Embedding %d chunks (this may take several minutes)...", len(chunks))
        store = FAISS.from_documents(chunks, get_embedding_model())

        target.mkdir(parents=True, exist_ok=True)
        store.save_local(str(target))
        logger.info("Vector store saved to %s (%d vectors)", target, store.index.ntotal)
        return store
    except Exception as exc:  # noqa: BLE001
        raise VectorStoreError("Failed to build or persist the FAISS index", exc) from exc


def load_vector_store() -> FAISS:
    """Load the persisted FAISS index."""
    target = Path(settings.vectorstore_dir)

    if not index_exists(target):
        raise VectorStoreError(
            f"No FAISS index at {target}. "
            "Build it first with: python -m app.ingestion.build_index"
        )

    try:
        logger.info("Loading FAISS index from %s", target)
        store = FAISS.load_local(
            str(target),
            get_embedding_model(),
            # Safe here: this artefact is produced by our own build step,
            # never accepted from an untrusted source.
            allow_dangerous_deserialization=True,
        )
        logger.info("FAISS index loaded (%d vectors).", store.index.ntotal)
        return store
    except Exception as exc:  # noqa: BLE001
        raise VectorStoreError(f"Failed to load FAISS index from {target}", exc) from exc
