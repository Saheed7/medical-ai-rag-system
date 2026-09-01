"""Tests for prompt construction, citation formatting and engine plumbing."""

from __future__ import annotations

from langchain_core.documents import Document

from app.rag.engine import Citation, RAGResponse, _format_context, _to_citation
from app.rag.prompts import (
    MEDICAL_DISCLAIMER,
    NO_ANSWER_SENTINEL,
    build_rag_prompt,
)


class TestPrompts:
    def test_prompt_declares_required_variables(self):
        assert set(build_rag_prompt().input_variables) == {"context", "question"}

    def test_prompt_renders_both_inputs(self):
        rendered = build_rag_prompt().format(context="CTX", question="Q?")
        assert "CTX" in rendered and "Q?" in rendered

    def test_guardrail_strings_present(self):
        assert NO_ANSWER_SENTINEL
        assert "healthcare professional" in MEDICAL_DISCLAIMER


class TestContextFormatting:
    def test_context_is_numbered_and_attributed(self, sample_documents):
        context = _format_context(sample_documents)
        assert "[Excerpt 1 | gale.pdf, page 1042]" in context
        assert "[Excerpt 2 | gale.pdf, page 1873]" in context

    def test_citation_truncates_long_snippets(self):
        doc = Document(page_content="x" * 900, metadata={"source": "s.pdf", "page": 7})
        citation = _to_citation(doc, max_chars=100)
        assert citation.snippet.endswith("...")
        assert len(citation.snippet) <= 104
        assert citation.page == 7

    def test_citation_renders_readably(self):
        c = Citation(source="gale.pdf", page=12, snippet="text")
        assert "gale.pdf" in c.render() and "p. 12" in c.render()


class TestRAGResponse:
    def test_defaults_to_no_citations(self):
        assert RAGResponse(answer="hi").has_citations is False

    def test_detects_citations(self):
        r = RAGResponse(answer="hi", citations=[Citation("a.pdf", 1, "s")])
        assert r.has_citations is True
