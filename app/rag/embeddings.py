"""Embedding model provider (loaded once per process)."""

from __future__ import annotations

from functools import lru_cache

from langchain_huggingface import HuggingFaceEmbeddings

from app.core.config import settings
from app.core.exceptions import EmbeddingError
from app.core.logger import get_logger

logger = get_logger(__name__)


@lru_cache(maxsize=1)
def get_embedding_model() -> HuggingFaceEmbeddings:
    """Return a cached sentence-transformer embedding model.

    Cached because loading weights costs seconds and hundreds of MB; the
    reference implementation reloaded this on every user message.
    """
    try:
        logger.info("Loading embedding model: %s", settings.embedding_model_id)
        model = HuggingFaceEmbeddings(
            model_name=settings.embedding_model_id,
            model_kwargs={"device": settings.embedding_device},
            encode_kwargs={
                "normalize_embeddings": True,   # cosine similarity via inner product
                "batch_size": settings.embedding_batch_size,
            },
        )
        logger.info("Embedding model ready.")
        return model
    except Exception as exc:  # noqa: BLE001
        raise EmbeddingError(
            f"Could not load embedding model {settings.embedding_model_id!r}", exc
        ) from exc
