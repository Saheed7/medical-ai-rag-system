"""Language model provider backed by the Hugging Face Inference API."""

from __future__ import annotations

from functools import lru_cache

from langchain_huggingface import ChatHuggingFace, HuggingFaceEndpoint

from app.core.config import settings
from app.core.exceptions import ConfigurationError, LLMError
from app.core.logger import get_logger

logger = get_logger(__name__)


@lru_cache(maxsize=1)
def get_llm() -> ChatHuggingFace:
    """Return a cached chat model client.

    Wrapped in ChatHuggingFace so the model receives properly formatted chat
    turns rather than a flattened prompt string.
    """
    if not settings.hf_token:
        raise ConfigurationError(
            "HF_TOKEN is not set. Add it to your .env file or export it. "
            "Create a token at https://huggingface.co/settings/tokens"
        )

    try:
        logger.info(
            "Initialising LLM endpoint: %s (provider=%s)",
            settings.llm_repo_id, settings.llm_provider,
        )
        endpoint = HuggingFaceEndpoint(
            repo_id=settings.llm_repo_id,
            huggingfacehub_api_token=settings.hf_token,
            provider=settings.llm_provider,
            task="text-generation",
            temperature=settings.llm_temperature,
            max_new_tokens=settings.llm_max_new_tokens,
            timeout=settings.llm_timeout_seconds,
            repetition_penalty=1.03,
        )
        chat_model = ChatHuggingFace(llm=endpoint)
        logger.info("LLM client ready.")
        return chat_model
    except Exception as exc:  # noqa: BLE001
        raise LLMError(
            f"Failed to initialise LLM {settings.llm_repo_id!r} "
            f"via provider {settings.llm_provider!r}. "
            f"Run 'python scripts/check_llm.py' to list providers that actually "
            f"serve this model.",
            exc,
        ) from exc
