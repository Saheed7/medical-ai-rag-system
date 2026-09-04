"""Centralised, validated application configuration.

All tunables live here and are overridable via environment variables or a
local `.env` file. Using pydantic-settings gives us type coercion and
fail-fast validation at import time rather than a `KeyError` deep in a
request handler.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve to the repository root regardless of the current working directory.
PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Runtime configuration for the Medical AI RAG System."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ----- Application ---------------------------------------------------
    app_name: str = "Medical AI RAG System"
    app_version: str = "1.0.0"
    environment: str = Field(default="development")
    log_level: str = Field(default="INFO")

    # ----- Server --------------------------------------------------------
    host: str = "0.0.0.0"
    port: int = 8080

    # ----- Paths ---------------------------------------------------------
    data_dir: Path = PROJECT_ROOT / "data"
    vectorstore_dir: Path = PROJECT_ROOT / "vectorstore" / "faiss_index"
    logs_dir: Path = PROJECT_ROOT / "logs"

    # ----- Ingestion -----------------------------------------------------
    chunk_size: int = 800
    chunk_overlap: int = 120
    min_chunk_chars: int = 80  # discard fragments too small to be meaningful

    # ----- Embeddings ----------------------------------------------------
    embedding_model_id: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_device: str = "cpu"
    embedding_batch_size: int = 64

    # ----- Retrieval -----------------------------------------------------
    retrieval_top_k: int = 4
    retrieval_fetch_k: int = 20
    # Default chosen by measurement, not assumption. On the 32-question
    # evaluation set, plain similarity beats MMR at every k > 1
    # (96.9% vs 87.5% hit rate at k=4). See eval/README.md.
    retrieval_strategy: str = Field(default="similarity")  # "mmr" | "similarity"
    mmr_lambda: float = 0.5

    # ----- LLM -----------------------------------------------------------
    hf_token: str | None = Field(default=None, alias="HF_TOKEN")
    llm_repo_id: str = "meta-llama/Llama-3.1-8B-Instruct"
    # Hugging Face routes through third-party inference providers. "auto"
    # lets HF choose, but availability shifts; pin an explicit provider
    # (e.g. "together", "groq", "hf-inference") for reproducible behaviour.
    llm_provider: str = "auto"
    llm_temperature: float = 0.2
    llm_max_new_tokens: int = 512
    llm_timeout_seconds: int = 120

    # ----- Validators ----------------------------------------------------
    @field_validator("retrieval_strategy")
    @classmethod
    def _validate_strategy(cls, v: str) -> str:
        allowed = {"mmr", "similarity"}
        if v not in allowed:
            raise ValueError(f"retrieval_strategy must be one of {allowed}, got {v!r}")
        return v

    @field_validator("chunk_overlap")
    @classmethod
    def _validate_overlap(cls, v: int, info) -> int:
        chunk_size = info.data.get("chunk_size")
        if chunk_size is not None and v >= chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        return v

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"production", "prod"}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a process-wide singleton of the settings object."""
    return Settings()


settings = get_settings()
