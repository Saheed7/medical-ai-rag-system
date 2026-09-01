"""Per-stage PDF ingestion diagnostic.

Pinpoints exactly where text is lost: raw extraction, the LangChain loader,
or our cleaning pass.

Usage:
    python scripts/diagnose_pdf.py
    python scripts/diagnose_pdf.py path/to/file.pdf
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.ingestion.pdf_loader import clean_text  # noqa: E402

SAMPLE_PAGES = (0, 5, 50, 200, 400)
EXPECTED_MD5 = "53c0dd111a671875ab3e962d48af721a"
EXPECTED_BYTES = 12_226_938


def banner(title: str) -> None:
    print(f"\n{'=' * 62}\n{title}\n{'=' * 62}")


def check_file(path: Path) -> None:
    banner("1. FILE INTEGRITY")
    size = path.stat().st_size
    digest = hashlib.md5(path.read_bytes()).hexdigest()

    print(f"  path : {path}")
    print(f"  size : {size:,} bytes ({size / 1_048_576:.2f} MB)")
    print(f"  md5  : {digest}")

    if path.name.startswith("The_GALE_ENCYCLOPEDIA"):
        size_ok = size == EXPECTED_BYTES
        hash_ok = digest == EXPECTED_MD5
        print(f"  expected size match : {'YES' if size_ok else 'NO  <-- PROBLEM'}")
        print(f"  expected md5 match  : {'YES' if hash_ok else 'NO  <-- PROBLEM'}")
        if not (size_ok and hash_ok):
            print("\n  >> The file differs from the known-good copy.")
            print("  >> Re-copy the PDF into data/ and re-run this script.")


def check_raw(path: Path) -> bool:
    banner("2. RAW pypdf EXTRACTION")
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    print(f"  pages detected: {len(reader.pages)}")

    any_text = False
    for i in SAMPLE_PAGES:
        if i >= len(reader.pages):
            continue
        text = reader.pages[i].extract_text() or ""
        any_text = any_text or bool(text.strip())
        preview = " ".join(text.split())[:70]
        print(f"  page {i:>4}: {len(text):>6} chars | {preview}")

    if not any_text:
        print("\n  >> No text at ANY sampled page.")
        print("  >> The file is corrupt/truncated, or is a scan needing OCR.")
    return any_text


def check_loader(path: Path) -> None:
    banner("3. LANGCHAIN PyPDFLoader")
    from langchain_community.document_loaders import PyPDFLoader

    pages = PyPDFLoader(str(path)).load()
    lengths = [len(p.page_content or "") for p in pages]
    empty = sum(1 for n in lengths if n == 0)
    print(f"  documents returned : {len(pages)}")
    print(f"  empty pages        : {empty}")
    print(f"  non-empty pages    : {len(pages) - empty}")
    if lengths:
        print(f"  mean chars/page    : {sum(lengths) / len(lengths):.0f}")


def check_cleaning(path: Path) -> None:
    banner("4. CLEANING PASS")
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    print(f"  min_chunk_chars threshold: {settings.min_chunk_chars}")

    for i in SAMPLE_PAGES:
        if i >= len(reader.pages):
            continue
        raw = reader.pages[i].extract_text() or ""
        cleaned = clean_text(raw)
        verdict = "KEPT" if len(cleaned) >= settings.min_chunk_chars else "DROPPED"
        print(f"  page {i:>4}: {len(raw):>6} raw -> {len(cleaned):>6} cleaned  [{verdict}]")


def main() -> None:
    if len(sys.argv) > 1:
        path = Path(sys.argv[1])
    else:
        pdfs = sorted(Path(settings.data_dir).glob("*.pdf"))
        if not pdfs:
            print(f"No PDFs found in {settings.data_dir}")
            sys.exit(1)
        path = pdfs[0]

    if not path.exists():
        print(f"File not found: {path}")
        sys.exit(1)

    check_file(path)
    if check_raw(path):
        check_loader(path)
        check_cleaning(path)
        banner("RESULT")
        print("  Raw extraction works. If the build still fails, the cleaning")
        print("  threshold is the culprit — see stage 4 above.")
    else:
        banner("RESULT")
        print("  Extraction failed at the source. Replace the PDF; the rest of")
        print("  the pipeline cannot recover text that is not in the file.")


if __name__ == "__main__":
    main()
