"""Validate the no-answer guardrail.

Asks questions the corpus cannot answer and checks the system emits the
refusal sentinel rather than improvising. This exercises the most important
safety property of a citation-bound system: knowing when to say nothing.

Unlike the retrieval evaluation, this DOES call the LLM, so it costs tokens
and takes roughly a second per question.

Usage:
    python scripts/evaluate_refusal.py
    python scripts/evaluate_refusal.py --verbose     # print each answer
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import PROJECT_ROOT  # noqa: E402
from app.rag.prompts import NO_ANSWER_SENTINEL  # noqa: E402

PROBES_PATH = PROJECT_ROOT / "eval" / "refusal_questions.json"


def main() -> None:
    ap = argparse.ArgumentParser(description="Validate the refusal guardrail.")
    ap.add_argument("--verbose", action="store_true", help="Print every answer")
    args = ap.parse_args()

    if not PROBES_PATH.exists():
        sys.exit(f"No probe set at {PROBES_PATH}")

    probes = json.loads(PROBES_PATH.read_text(encoding="utf-8"))["questions"]

    from app.rag.engine import get_engine  # noqa: PLC0415

    engine = get_engine()
    engine.warm_up()

    refused, answered = [], []
    started = time.perf_counter()

    print(f"Probing {len(probes)} out-of-corpus questions...\n")
    for probe in probes:
        response = engine.answer(probe["question"])
        # `grounded` is False when the engine detected the sentinel and
        # suppressed citations - that is the behaviour under test.
        did_refuse = (
            not response.grounded
            or NO_ANSWER_SENTINEL.lower() in response.answer.lower()
        )
        (refused if did_refuse else answered).append((probe, response))

        mark = "REFUSED " if did_refuse else "ANSWERED"
        print(f"  {mark} {probe['id']}: {probe['question']}")
        if args.verbose or not did_refuse:
            print(f"           -> {response.answer[:150].strip()}")

    total = len(probes)
    rate = len(refused) / total if total else 0.0

    print(f"\nRefusal rate: {len(refused)}/{total} = {rate:.0%}")
    print(f"Completed in {time.perf_counter() - started:.1f}s")

    if answered:
        print(
            "\nQuestions that were answered instead of refused are guardrail "
            "failures. Inspect whether retrieval surfaced spurious context, or "
            "whether the prompt's refusal instruction needs strengthening."
        )
    sys.exit(0 if not answered else 1)


if __name__ == "__main__":
    main()
