"""Typed exception hierarchy.

Distinct types let callers (and the UI layer) react differently to a missing
index versus an upstream LLM outage, instead of parsing error strings.
"""

from __future__ import annotations


class MedicalRAGError(Exception):
    """Base class for every error raised by this application."""

    def __init__(self, message: str, cause: Exception | None = None) -> None:
        self.message = message
        self.cause = cause
        super().__init__(self.__str__())

    def __str__(self) -> str:
        if self.cause is not None:
            return f"{self.message} | caused by {type(self.cause).__name__}: {self.cause}"
        return self.message


class ConfigurationError(MedicalRAGError):
    """Missing or invalid configuration (e.g. absent API token)."""


class DocumentIngestionError(MedicalRAGError):
    """Raised when source PDFs cannot be read, parsed or chunked."""


class VectorStoreError(MedicalRAGError):
    """Raised when the FAISS index cannot be built, saved or loaded."""


class EmbeddingError(MedicalRAGError):
    """Raised when the embedding model fails to load or encode."""


class LLMError(MedicalRAGError):
    """Raised when the language model endpoint fails or times out."""


class RetrievalError(MedicalRAGError):
    """Raised when the retrieval step fails."""
