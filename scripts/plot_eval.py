"""Render evaluation figures from a retrieval sweep.

Produces three plots that are meaningful for a retrieval system:

  1. retrieval_vs_k.png   hit rate (recall@k) and MRR as k varies
  2. precision_recall.png the precision/recall trade-off across k
  3. mmr_lambda_heatmap.png  MMR hit rate over the lambda x k grid

Deliberately NOT produced: training/validation curves (nothing is trained --
the embedding model is pretrained and frozen) and ROC curves (the refusal
decision is sentinel detection, not a tunable score threshold
sweeping an
invented threshold would misrepresent the system).

Usage:
    python scripts/plot_eval.py                    # measure, then plot
    python scripts/plot_eval.py --from results.json  # replot saved measurements
    python scripts/plot_eval.py --no-heatmap       # skip the slow lambda sweep
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    import matplotlib  # noqa: E402

    matplotlib.use("Agg")  # headless: no display needed in CI or a container
    import matplotlib.pyplot as plt  # noqa: E402
except ImportError:  # pragma: no cover - environment guard
    sys.exit(
        "matplotlib is required to render figures but is not installed.\n"
        "  pip install matplotlib\n"
        "or install the full dev set:\n"
        "  pip install -r requirements-dev.txt\n\n"
        "It is intentionally a dev-only dependency: the runtime image never "
        "plots, so it adds nothing to the deployed container."
    )

from app.core.config import PROJECT_ROOT  # noqa: E402

OUT_DIR = PROJECT_ROOT / "docs" / "images"
DATA_PATH = PROJECT_ROOT / "eval" / "sweep.json"

INK = "#1f2933"
ACCENT = "#0f766e"
ALT = "#b45309"


def measure(ks: list[int], lambdas: list[float], do_heatmap: bool) -> dict:
    from scripts.evaluate_retrieval import evaluate, load_questions, metrics

    questions = load_questions()
    data: dict = {"n_questions": len(questions), "ks": ks, "curves": {}, "heatmap": {}}

    for strategy in ("similarity", "mmr"):
        rows = []
        for k in ks:
            results = evaluate(questions, strategy, k, 0.5, 20)
            m0 = metrics(results, tolerance=0)
            m1 = metrics(results, tolerance=1)
            # Precision@k: one relevant page per question, so a hit contributes
            # at most 1/k. This is the ceiling that makes the trade-off visible.
            rows.append({
                "k": k,
                "hit_rate": m0["hit_rate"],
                "mrr": m0["mrr"],
                "hit_rate_tol1": m1["hit_rate"],
                "precision": m0["hit_rate"] / k,
            })
            print(f"  {strategy:10} k={k:<2} hit={m0['hit_rate']:.1%} "
                  f"mrr={m0['mrr']:.3f} (tol1 hit={m1['hit_rate']:.1%})")
        data["curves"][strategy] = rows

    if do_heatmap:
        print("\n  MMR lambda sweep:")
        for lam in lambdas:
            row = []
            for k in ks:
                results = evaluate(questions, "mmr", k, lam, 20)
                row.append(metrics(results, tolerance=0)["hit_rate"])
            data["heatmap"][str(lam)] = row
            print(f"    lambda={lam:<4} " + " ".join(f"{v:.2f}" for v in row))

    return data


def plot_vs_k(data: dict) -> Path:
    ks = data["ks"]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.2))

    for name, colour, marker in (("similarity", ACCENT, "o"), ("mmr", ALT, "s")):
        rows = data["curves"][name]
        ax1.plot(ks, [r["hit_rate"] * 100 for r in rows], marker=marker,
                 color=colour, label=name, linewidth=2)
        ax2.plot(ks, [r["mrr"] for r in rows], marker=marker,
                 color=colour, label=name, linewidth=2)

    ax1.set_xlabel("k (chunks retrieved)")
    ax1.set_ylabel("Hit rate @k  (%)")
    ax1.set_title("Recall@k", color=INK)
    ax1.set_ylim(0, 105)
    ax1.grid(alpha=.25)
    ax1.legend()

    ax2.set_xlabel("k (chunks retrieved)")
    ax2.set_ylabel("MRR")
    ax2.set_title("Mean reciprocal rank", color=INK)
    ax2.set_ylim(0, 1)
    ax2.grid(alpha=.25)
    ax2.legend()

    fig.suptitle(f"Retrieval quality vs k  ({data['n_questions']} labelled questions)",
                 color=INK, fontsize=12)
    fig.tight_layout()
    out = OUT_DIR / "retrieval_vs_k.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_precision_recall(data: dict) -> Path:
    fig, ax = plt.subplots(figsize=(6.2, 4.6))
    for name, colour, marker in (("similarity", ACCENT, "o"), ("mmr", ALT, "s")):
        rows = data["curves"][name]
        ax.plot([r["hit_rate"] * 100 for r in rows], [r["precision"] * 100 for r in rows],
                marker=marker, color=colour, label=name, linewidth=2)
        for r in rows:
            ax.annotate(f"k={r['k']}", (r["hit_rate"] * 100, r["precision"] * 100),
                        textcoords="offset points", xytext=(6, 5), fontsize=8, color=colour)
    ax.set_xlabel("Recall @k  (%)")
    ax.set_ylabel("Precision @k  (%)")
    ax.set_title("Precision / recall trade-off across k", color=INK)
    ax.grid(alpha=.25)
    ax.legend()
    fig.tight_layout()
    out = OUT_DIR / "precision_recall.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_heatmap(data: dict) -> Path | None:
    if not data.get("heatmap"):
        return None
    lambdas = sorted(data["heatmap"], key=float)
    grid = [[v * 100 for v in data["heatmap"][lam]] for lam in lambdas]
    ks = data["ks"]

    fig, ax = plt.subplots(figsize=(6.6, 4.4))
    im = ax.imshow(grid, cmap="YlGnBu", aspect="auto", vmin=50, vmax=100)
    ax.set_xticks(range(len(ks)), [str(k) for k in ks])
    ax.set_yticks(range(len(lambdas)), lambdas)
    ax.set_xlabel("k (chunks retrieved)")
    ax.set_ylabel("MMR λ  (0 = max diversity)")
    ax.set_title("MMR hit rate across λ and k  (%)", color=INK)
    for i in range(len(lambdas)):
        for j in range(len(ks)):
            v = grid[i][j]
            ax.text(j, i, f"{v:.0f}", ha="center", va="center",
                    color="white" if v > 82 else INK, fontsize=9)
    fig.colorbar(im, ax=ax, label="hit rate (%)")
    fig.tight_layout()
    out = OUT_DIR / "mmr_lambda_heatmap.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Render evaluation figures.")
    ap.add_argument("--from", dest="src", type=Path, help="Replot saved measurements")
    ap.add_argument("--no-heatmap", action="store_true")
    ap.add_argument("--ks", type=int, nargs="+", default=[1, 2, 3, 4, 6, 8, 10])
    ap.add_argument("--lambdas", type=float, nargs="+",
                    default=[0.0, 0.25, 0.5, 0.75, 1.0])
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if args.src:
        data = json.loads(args.src.read_text(encoding="utf-8"))
    else:
        print("Measuring...")
        data = measure(args.ks, args.lambdas, not args.no_heatmap)
        DATA_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"\nMeasurements saved to {DATA_PATH}")

    written = [plot_vs_k(data), plot_precision_recall(data), plot_heatmap(data)]
    print("\nFigures written:")
    for p in written:
        if p:
            print(f"  {p.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
