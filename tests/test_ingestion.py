"""Tests for PDF text cleaning and chunking."""

from __future__ import annotations

import pytest

from app.core.exceptions import DocumentIngestionError
from app.ingestion.chunker import build_splitter, chunk_documents
from app.ingestion.pdf_loader import clean_text


class TestCleanText:
    def test_rejoins_hyphenated_line_breaks(self):
        assert "hypertension" in clean_text("hyper-\ntension is common")

    def test_collapses_excess_whitespace(self):
        assert clean_text("word     other") == "word other"

    def test_collapses_excess_newlines(self):
        assert clean_text("a\n\n\n\n\nb") == "a\n\nb"

    def test_strips_running_header(self):
        cleaned = clean_text("GALE ENCYCLOPEDIA OF MEDICINE 2\nReal content here")
        assert "GALE ENCYCLOPEDIA" not in cleaned
        assert "Real content here" in cleaned


class TestChunker:
    def test_splitter_respects_configured_size(self):
        splitter = build_splitter()
        assert splitter._chunk_size > splitter._chunk_overlap

    def test_chunking_assigns_sequential_ids(self, sample_documents):
        chunks = chunk_documents(sample_documents)
        ids = [c.metadata["chunk_id"] for c in chunks]
        assert ids == list(range(len(chunks)))

    def test_chunking_preserves_page_metadata(self, sample_documents):
        chunks = chunk_documents(sample_documents)
        assert all("page" in c.metadata for c in chunks)
        assert {c.metadata["page"] for c in chunks} <= {1042, 1873}

    def test_empty_input_raises(self):
        with pytest.raises(DocumentIngestionError):
            chunk_documents([])
