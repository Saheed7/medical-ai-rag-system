"""Configuration validation tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings


def test_settings_defaults_are_sane():
    s = get_settings()
    assert s.chunk_overlap < s.chunk_size
    assert s.retrieval_top_k > 0
    assert s.retrieval_fetch_k >= s.retrieval_top_k
    assert s.port > 0


def test_settings_is_cached_singleton():
    assert get_settings() is get_settings()


def test_invalid_retrieval_strategy_rejected():
    with pytest.raises(ValidationError):
        Settings(retrieval_strategy="random_walk")


def test_overlap_must_be_smaller_than_chunk_size():
    with pytest.raises(ValidationError):
        Settings(chunk_size=100, chunk_overlap=500)


def test_production_flag():
    assert Settings(environment="production").is_production is True
    assert Settings(environment="development").is_production is False
