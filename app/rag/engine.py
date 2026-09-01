"""The RAG engine: retrieval + grounded generation, loaded once per process."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import Lock

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser

from app.core.config import settings
from app.core.exceptions import MedicalRAGError, RetrievalError
from app.core.logger import get_logger
from app.rag.llm import get_llm
from app.rag.prompts import NO_ANSWER_SENTINEL, build_rag_prompt
from app.rag.vector_store import load_vector_store

logger = get_logger(__name__)


@dataclass(frozen=True)
class Citation:
    """A single retrieved passage, surfaced to the user for verification."""

    source: str
    page: int
    snippet: str
    score: float | None = None

    def render(self) -> str:
        return f"**{self.source}**, p. {self.page} — {self.snippet}"


@dataclass
class RAGResponse:
    """Everything the UI needs to render one answer."""

    answer: str
    citations: list[Citation] = field(default_factory=list)
    latency_ms: float = 0.0
    grounded: bool = True

    @property
    def has_citations(self) -> bool:
        return bool(self.citations)


def _format_context(documents: list[Document]) -> str:
    """Render retrieved chunks into a numbered block for the prompt."""
    parts = []
    for i, doc in enumerate(documents, start=1):
        source = doc.metadata.get("source", "unknown")
        page = doc.metadata.get("page", "?")
        parts.append(f"[Excerpt {i} | {source}, page {page}]\n{doc.page_content}")
    return "\n\n".join(parts)


def _to_citation(doc: Document, max_chars: int = 260) -> Citation:
    text = " ".join(doc.page_content.split())
    snippet = text[:max_chars] + ("..." if len(text) > max_chars else "")
    return Citation(
        source=str(doc.metadata.get("source", "unknown")),
        page=int(doc.metadata.get("page", 0)),
        snippet=snippet,
    )


class RAGEngine:
    """Thread-safe, lazily initialised retrieval-augmented generation engine."""

    _instance: RAGEngine | None = None
    _lock = Lock()

    def __init__(self) -> None:
        self._vector_store = None
        self._retriever = None
        self._chain = None
        self._ready = False

    # -- lifecycle --------------------------------------------------------
    @classmethod
    def instance(cls) -> RAGEngine:
        """Return the process-wide singleton, creating it if necessary."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def _ensure_retriever(self) -> None:
        """Load the FAISS index and build the retriever (idempotent)."""
        if self._retriever is not None:
            return

        self._vector_store = load_vector_store()

        if settings.retrieval_strategy == "mmr":
            # MMR trades a little relevance for diversity, which reduces
            # near-duplicate excerpts from adjacent pages.
            search_kwargs = {
                "k": settings.retrieval_top_k,
                "fetch_k": settings.retrieval_fetch_k,
                "lambda_mult": settings.mmr_lambda,
            }
        else:
            search_kwargs = {"k": settings.retrieval_top_k}

        self._retriever = self._vector_store.as_retriever(
            search_type=settings.retrieval_strategy,
            search_kwargs=search_kwargs,
        )

    def _ensure_chain(self) -> None:
        """Build the generation chain (idempotent)."""
        if self._chain is not None:
            return
        self._chain = build_rag_prompt() | get_llm() | StrOutputParser()

    def warm_up(self) -> None:
        """Load index, embeddings and LLM. Call once at application start.

        Each component is cached independently, so a recoverable failure in
        one stage (e.g. a missing HF_TOKEN) does not force the expensive
        FAISS reload on every subsequent request.
        """
        if self._ready:
            return

        with self._lock:
            if self._ready:
                return

            started = time.perf_counter()
            logger.info("Warming up RAG engine...")

            self._ensure_retriever()
            self._ensure_chain()
            self._ready = True

            logger.info(
                "RAG engine ready in %.1fs (strategy=%s, k=%d)",
                time.perf_counter() - started,
                settings.retrieval_strategy,
                settings.retrieval_top_k,
            )

    @property
    def is_ready(self) -> bool:
        return self._ready

    def health(self) -> dict[str, object]:
        """Lightweight status payload for liveness/readiness probes."""
        return {
            "status": "ok" if self._ready else "degraded",
            "retriever_ready": self._retriever is not None,
            "llm_ready": self._chain is not None,
            "version": settings.app_version,
            "environment": settings.environment,
            "vectors": int(self._vector_store.index.ntotal) if self._vector_store else 0,
            "embedding_model": settings.embedding_model_id,
            "llm": settings.llm_repo_id,
        }

    # -- inference --------------------------------------------------------
    def retrieve(self, question: str) -> list[Document]:
        try:
            return self._retriever.invoke(question)
        except Exception as exc:  # noqa: BLE001
            raise RetrievalError("Retrieval step failed", exc) from exc

    def answer(self, question: str) -> RAGResponse:
        """Answer a question against the indexed corpus."""
        if not question or not question.strip():
            return RAGResponse(answer="Please enter a question.", grounded=False)

        self.warm_up()
        question = question.strip()
        started = time.perf_counter()

        try:
            documents = self.retrieve(question)

            if not documents:
                logger.info("No documents retrieved for: %r", question)
                return RAGResponse(
                    answer=NO_ANSWER_SENTINEL,
                    latency_ms=(time.perf_counter() - started) * 1000,
                    grounded=False,
                )

            answer_text = self._chain.invoke(
                {"context": _format_context(documents), "question": question}
            ).strip()

            grounded = NO_ANSWER_SENTINEL.lower() not in answer_text.lower()
            # Only cite sources when the model actually used them.
            citations = [_to_citation(d) for d in documents] if grounded else []

            latency_ms = (time.perf_counter() - started) * 1000
            logger.info(
                "Answered in %.0fms | grounded=%s | docs=%d | q=%r",
                latency_ms, grounded, len(documents), question[:80],
            )

            return RAGResponse(
                answer=answer_text,
                citations=citations,
                latency_ms=latency_ms,
                grounded=grounded,
            )

        except MedicalRAGError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise MedicalRAGError("Unexpected failure while answering", exc) from exc


def get_engine() -> RAGEngine:
    """Convenience accessor for the singleton engine."""
    return RAGEngine.instance()
