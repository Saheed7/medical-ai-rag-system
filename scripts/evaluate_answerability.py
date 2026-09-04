"""Confusion matrix for the answer/refuse decision.

Two classes with ground truth:
  - 32 in-corpus questions  -> the system SHOULD answer
  - 10 out-of-corpus probes -> the system SHOULD refuse

That makes answerability a genuine binary classification task, so a confusion
matrix, precision, recall and F1 are meaningful here in a way they are not for
the retrieval stage.

The two error types differ sharply in cost:
  - False answer   (answered an unanswerable question) -> hallucination risk
  - False refusal  (refused an answerable question)    -> merely unhelpful

For a citation-bound medical system, false answers are the serious failure.

Calls the LLM once per question (~42 calls, roughly a minute).

Usage:
    python scripts/evaluate_answerability.py
    python scripts/evaluate_answerability.py --plot
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

EVAL_DIR = PROJECT_ROOT / "eval"
OUT_DIR = PROJECT_ROOT / "docs" / "images"


def refused(response) -> bool:
    return (
        not response.grounded
        or NO_ANSWER_SENTINEL.lower() in response.answer.lower()
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Answerability confusion matrix.")
    ap.add_argument("--plot", action="store_true", help="Write a confusion matrix PNG")
    args = ap.parse_args()

    in_corpus = json.loads((EVAL_DIR / "questions.json").read_text(encoding="utf-8"))["questions"]
    out_corpus = json.loads((EVAL_DIR / "refusal_questions.json").read_text(encoding="utf-8"))["questions"]

    from app.rag.engine import get_engine  # noqa: PLC0415

    engine = get_engine()
    engine.warm_up()

    started = time.perf_counter()
    tp = fn = 0   # in-corpus: answered (correct) / refused (false refusal)
    tn = fp = 0   # out-of-corpus: refused (correct) / answered (false answer)
    false_answers, false_refusals = [], []

    print(f"Evaluating {len(in_corpus)} answerable + {len(out_corpus)} unanswerable...\n")

    for q in in_corpus:
        r = engine.answer(q["question"])
        if refused(r):
            fn += 1
            false_refusals.append(q["question"])
        else:
            tp += 1

    for q in out_corpus:
        r = engine.answer(q["question"])
        if refused(r):
            tn += 1
        else:
            fp += 1
            false_answers.append((q["question"], r.answer[:120]))

    total = tp + fn + tn + fp
    accuracy = (tp + tn) / total if total else 0.0
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    print("Confusion matrix (positive class = 'answered')\n")
    print("                    predicted answer   predicted refuse")
    print(f"  actually answerable   {tp:>10}        {fn:>10}")
    print(f"  actually unanswerable {fp:>10}        {tn:>10}")
    print(f"\n  accuracy  {accuracy:.1%}")
    print(f"  precision {precision:.3f}   (of answers given, how many were answerable)")
    print(f"  recall    {recall:.3f}   (of answerable questions, how many were answered)")
    print(f"  F1        {f1:.3f}")
    print(f"\n  false answers  (hallucination risk): {fp}")
    print(f"  false refusals (merely unhelpful):   {fn}")
    print(f"\nCompleted in {time.perf_counter() - started:.1f}s")

    for question, answer in false_answers:
        print(f"\n  FALSE ANSWER: {question}\n    -> {answer}")
    for question in false_refusals:
        print(f"\n  FALSE REFUSAL: {question}")

    payload = {
        "tp": tp, "fn": fn, "fp": fp, "tn": tn,
        "accuracy": accuracy, "precision": precision, "recall": recall, "f1": f1,
    }
    (EVAL_DIR / "answerability.json").write_text(json.dumps(payload, indent=2))
    print(f"\nSaved to {EVAL_DIR / 'answerability.json'}")

    if args.plot:
        try:
            import matplotlib  # noqa: PLC0415

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt  # noqa: PLC0415
        except ImportError:
            print("\nmatplotlib not installed; skipping the figure.")
            print("  pip install matplotlib")
            return

        grid = [[tp, fn], [fp, tn]]
        fig, ax = plt.subplots(figsize=(5.4, 4.4))
        im = ax.imshow(grid, cmap="YlGnBu")
        ax.set_xticks([0, 1], ["answered", "refused"])
        ax.set_yticks([0, 1], ["answerable\n(in corpus)", "unanswerable\n(out of corpus)"])
        ax.set_xlabel("system decision")
        ax.set_ylabel("ground truth")
        ax.set_title("Answerability decision", color="#1f2933")
        peak = max(max(row) for row in grid) or 1
        for i in range(2):
            for j in range(2):
                ax.text(j, i, str(grid[i][j]), ha="center", va="center",
                        fontsize=18,
                        color="white" if grid[i][j] > peak * 0.55 else "#1f2933")
        fig.colorbar(im, ax=ax, label="questions")
        fig.tight_layout()
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        out = OUT_DIR / "answerability_matrix.png"
        fig.savefig(out, dpi=150, bbox_inches="tight")
        plt.close(fig)
        print(f"Figure written to {out.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
