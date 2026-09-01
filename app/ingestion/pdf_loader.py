"""PDF discovery, loading and text normalisation."""

from __future__ import annotations

import re
from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader
from langchain_core.documents import Document

from app.core.config import settings
from app.core.exceptions import DocumentIngestionError
from app.core.logger import get_logger

logger = get_logger(__name__)

# Encyclopaedia scans carry running headers/footers and hyphenated line breaks.
# Cleaning these before chunking measurably improves retrieval quality.
_HYPHEN_LINEBREAK = re.compile(r"(\w)-\n(\w)")
_MULTI_WHITESPACE = re.compile(r"[ \t]{2,}")
_MULTI_NEWLINE = re.compile(r"\n{3,}")
_PAGE_ARTEFACT = re.compile(
    r"^\s*(GALE ENCYCLOPEDIA OF MEDICINE\s*\d*|\d+)\s*$",
    flags=re.IGNORECASE | re.MULTILINE,
)


def discover_pdfs(data_dir: Path | None = None) -> list[Path]:
    """Return every PDF in the data directory, sorted for deterministic runs."""
    directory = Path(data_dir or settings.data_dir)

    if not directory.exists():
        raise DocumentIngestionError(f"Data directory does not exist: {directory}")

    pdfs = sorted(directory.glob("*.pdf"))
    if not pdfs:
        raise DocumentIngestionError(
            f"No PDF files found in {directory}. "
            "Place the source corpus there before building the index."
        )

    logger.info("Discovered %d PDF file(s) in %s", len(pdfs), directory)
    return pdfs


def clean_text(text: str) -> str:
    """Normalise raw PDF text extraction artefacts."""
    text = _HYPHEN_LINEBREAK.sub(r"\1\2", text)   # re-join hyphenated words
    text = _PAGE_ARTEFACT.sub("", text)           # strip running headers/page numbers
    text = _MULTI_WHITESPACE.sub(" ", text)
    text = _MULTI_NEWLINE.sub("\n\n", text)
    return text.strip()


def load_documents(data_dir: Path | None = None) -> list[Document]:
    """Load and clean every page of every PDF into LangChain Documents."""
    pdfs = discover_pdfs(data_dir)
    documents: list[Document] = []

    for pdf_path in pdfs:
        try:
            pages = PyPDFLoader(str(pdf_path)).load()
        except Exception as exc:  # noqa: BLE001 - surface as a typed domain error
            raise DocumentIngestionError(f"Failed to parse {pdf_path.name}", exc) from exc

        kept = 0
        for page in pages:
            cleaned = clean_text(page.page_content)
            if len(cleaned) < settings.min_chunk_chars:
                continue  # blank or near-blank page
            page.page_content = cleaned
            page.metadata.update(
                {
                    "source": pdf_path.name,
                    # PyPDF pages are 0-indexed; humans cite from 1.
                    "page": int(page.metadata.get("page", 0)) + 1,
                }
            )
            documents.append(page)
            kept += 1

        logger.info("%s -> %d usable pages (of %d)", pdf_path.name, kept, len(pages))

    if not documents:
        raise DocumentIngestionError("All PDFs parsed but no extractable text was found.")

    logger.info("Loaded %d total pages across %d document(s)", len(documents), len(pdfs))
    return documents
