"""Measure retrieval quality against a labelled question set.

Reports hit-rate@k and MRR, and sweeps retrieval strategy and k so the
configured defaults are chosen from measurement rather than assertion.

Retrieval-only by default: no LLM calls, no cost, runs in seconds.

Usage:
    python scripts/evaluate_retrieval.py                 # sweep, print tables
    python scripts/evaluate_retrieval.py --k 4           # single configuration
    python scripts/evaluate_retrieval.py --failures      # show missed questions
    python scripts/evaluate_retrieval.py --audit         # re-verify the labels
    python scripts/evaluate_retrieval.py --markdown out.md
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import PROJECT_ROOT, settings  # noqa: E402

QUESTIONS_PATH = PROJECT_ROOT / "eval" / "questions.json"


@dataclass
class QueryResult:
    qid: str
    question: str
    relevant: set[int]
    retrieved: list[int]

    def first_hit_rank(self, tolerance: int = 0) -> int | None:
        """1-based rank of the first relevant page, or None."""
        for rank, page in enumerate(self.retrieved, start=1):
            if any(abs(page - r) <= tolerance for r in self.relevant):
                return rank
        return None


def load_questions() -> list[dict]:
    if not QUESTIONS_PATH.exists():
        sys.exit(f"No question set at {QUESTIONS_PATH}")
    return json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))["questions"]


@lru_cache(maxsize=1)
def _store():
    """Load the index once for the whole sweep, not once per configuration."""
    from app.rag.vector_store import load_vector_store  # noqa: PLC0415

    return load_vector_store()


def build_retriever(strategy: str, k: int, lambda_mult: float, fetch_k: int):
    store = _store()
    if strategy == "mmr":
        kwargs = {"k": k, "fetch_k": fetch_k, "lambda_mult": lambda_mult}
    else:
        kwargs = {"k": k}
    return store.as_retriever(search_type=strategy, search_kwargs=kwargs)


def evaluate(questions, strategy: str, k: int, lambda_mult: float, fetch_k: int):
    retriever = build_retriever(strategy, k, lambda_mult, fetch_k)
    results: list[QueryResult] = []
    for q in questions:
        docs = retriever.invoke(q["question"])
        results.append(
            QueryResult(
                qid=q["id"],
                question=q["question"],
                relevant=set(q["relevant_pages"]),
                retrieved=[int(d.metadata.get("page", -1)) for d in docs],
            )
        )
    return results


def metrics(results: list[QueryResult], tolerance: int = 0) -> dict[str, float]:
    ranks = [r.first_hit_rank(tolerance) for r in results]
    hits = [r for r in ranks if r is not None]
    return {
        "hit_rate": len(hits) / len(ranks) if ranks else 0.0,
        "mrr": sum(1.0 / r for r in hits) / len(ranks) if ranks else 0.0,
        "mean_rank_of_hit": statistics.mean(hits) if hits else float("nan"),
        "n": len(ranks),
        "misses": len(ranks) - len(hits),
    }


def fmt_row(label: str, m: dict) -> str:
    return (
        f"| {label} | {m['hit_rate']:.1%} | {m['mrr']:.3f} | "
        f"{m['mean_rank_of_hit']:.2f} | {m['misses']} |"
    )


def audit(questions) -> None:
    """Re-verify that each label's anchor term is on the labelled page."""
    from app.ingestion.pdf_loader import load_documents  # noqa: PLC0415

    by_page: dict[int, str] = {}
    for doc in load_documents():
        p = int(doc.metadata["page"])
        by_page[p] = by_page.get(p, "") + " " + doc.page_content.lower()

    bad = []
    for q in questions:
        page = q["relevant_pages"][0]
        anchor = q.get("anchor", "").lower()
        if not anchor:
            continue
        if anchor not in by_page.get(page, ""):
            bad.append((q["id"], page, anchor))

    print(f"Audited {len(questions)} labels against the ingested corpus.")
    if bad:
        print("Labels whose anchor was NOT found on the labelled page:")
        for qid, page, anchor in bad:
            print(f"  {qid}: expected {anchor!r} on page {page}")
        sys.exit(1)
    print("All labels verified.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Evaluate retrieval quality.")
    ap.add_argument("--k", type=int, help="Evaluate a single k instead of sweeping")
    ap.add_argument("--strategy", choices=["mmr", "similarity"])
    ap.add_argument("--lambda-mult", type=float, default=settings.mmr_lambda)
    ap.add_argument("--fetch-k", type=int, default=settings.retrieval_fetch_k)
    ap.add_argument("--tolerance", type=int, default=0,
                    help="Count an adjacent page as relevant (entries span pages)")
    ap.add_argument("--failures", action="store_true", help="List missed questions")
    ap.add_argument("--audit", action="store_true", help="Re-verify labels only")
    ap.add_argument("--markdown", type=Path, help="Write a markdown table here")
    args = ap.parse_args()

    questions = load_questions()

    if args.audit:
        audit(questions)
        return

    strategies = [args.strategy] if args.strategy else ["mmr", "similarity"]
    ks = [args.k] if args.k else [1, 2, 4, 8]

    print(f"Evaluating {len(questions)} questions "
          f"(embedding: {settings.embedding_model_id})\n")

    lines = [
        "| Configuration | Hit rate | MRR | Mean rank | Misses |",
        "|---|---:|---:|---:|---:|",
    ]
    detail: list[QueryResult] = []
    started = time.perf_counter()

    for strategy in strategies:
        for k in ks:
            results = evaluate(questions, strategy, k, args.lambda_mult, args.fetch_k)
            m = metrics(results, args.tolerance)
            label = f"`{strategy}`, k={k}"
            if strategy == "mmr":
                label += f", λ={args.lambda_mult}"
            lines.append(fmt_row(label, m))
            if k == settings.retrieval_top_k and strategy == settings.retrieval_strategy:
                detail = results

    table = "\n".join(lines)
    print(table)
    print(f"\nCompleted in {time.perf_counter() - started:.1f}s "
          f"(tolerance = ±{args.tolerance} page)")

    if args.failures and detail:
        print(f"\nMissed questions at the configured default "
              f"({settings.retrieval_strategy}, k={settings.retrieval_top_k}):")
        any_miss = False
        for r in detail:
            if r.first_hit_rank(args.tolerance) is None:
                any_miss = True
                print(f"  {r.qid}: {r.question}")
                print(f"    expected page(s) {sorted(r.relevant)}, got {r.retrieved}")
        if not any_miss:
            print("  none")

    if args.markdown:
        args.markdown.write_text(table + "\n", encoding="utf-8")
        print(f"\nMarkdown table written to {args.markdown}")


if __name__ == "__main__":
    main()
