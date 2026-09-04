# Evaluation

Retrieval quality and guardrail behaviour, measured rather than asserted.

## Question set

`questions.json` holds 32 questions drawn from across the corpus (pages 16–746),
each labelled with the page containing its answer. Labels were derived from the
entry definitions on those pages and machine-verified: the anchor term for each
question provably appears in the extracted text of its labelled page.

Re-verify at any time — useful after changing the ingestion pipeline:

```bash
python scripts/evaluate_retrieval.py --audit
```

## Retrieval evaluation

```bash
python scripts/evaluate_retrieval.py                    # sweep strategy x k
python scripts/evaluate_retrieval.py --failures         # show what missed
python scripts/evaluate_retrieval.py --markdown eval/results.md
```

No LLM calls, so it is free and runs in seconds.

**Metrics**

- **Hit rate@k** — fraction of questions where a relevant page appears in the top k. With one relevant page per question this is recall@k.
- **MRR** — mean reciprocal rank of the first relevant page. Rewards ranking the right page first, not merely somewhere in the list.
- **Mean rank of hit** — where relevant pages land when found.

**On tolerance.** Encyclopedia entries span page boundaries and chunks straddle
them, so a chunk answering the question may carry an adjacent page number.
`--tolerance 1` counts that as a hit. Report both: tolerance 0 is the strict
measure, tolerance 1 the charitable one. Quoting only the charitable number
without saying so would be misleading.

## Refusal evaluation

```bash
python scripts/evaluate_refusal.py
```

Asks 10 questions with no answer in the corpus and checks the system emits the
refusal sentinel. This calls the LLM, so it costs tokens.

A citation-bound system that answers anyway is worse than one that answers
nothing — this is the property most worth guarding.

## Measured results (2026-09-04)

32 questions, strict page matching, 4,932-vector index, ~11 s for the full sweep.

| Configuration | Hit rate | MRR | Misses |
|---|---:|---:|---:|
| `mmr`, k=4, λ=0.5 | 87.5% | 0.745 | 4 |
| **`similarity`, k=4** | **96.9%** | **0.807** | 1 |
| `similarity`, k=8 | 100.0% | 0.813 | 0 |

Full table in `results.md`. Refusal guardrail: **9/10 (90%)**.

**Outcome:** the default was `mmr` on the strength of an argument about
page-spanning entries. Similarity beat it at every k > 1, so the default in
`app/core/config.py` was changed to `similarity`. All four MMR misses retrieved
an *adjacent* page, so at `--tolerance 1` MMR k=4 also reaches 100%.

Caveat worth stating: these questions are definitional, with a single relevant
page each — the case that favours similarity. MMR may still win on multi-hop
questions, which this set does not yet contain.

## Interpreting results

A low hit rate points at ingestion or embedding, not the LLM: chunk size,
cleaning, or embedding model. A high hit rate with poor MRR means the right
page is retrieved but ranked low — a reranker would help. If `similarity` beats
`mmr`, the default should change; the point of measuring is to be willing to
act on it.

## Known limitations

- 32 questions is enough to compare configurations, not to establish confidence intervals.
- Questions are definitional, matching this corpus's structure. Multi-hop questions spanning entries are not represented.
- No groundedness scoring yet: whether each answer follows from retrieved context is unmeasured. That needs a judge model and is the next addition.


## Figures

Figure rendering needs matplotlib, which is a **dev-only** dependency — the
runtime image never plots:

```bash
pip install -r requirements-dev.txt
```

```bash
python scripts/plot_eval.py                     # curves + lambda heatmap
python scripts/evaluate_answerability.py --plot # confusion matrix
```

`plot_eval.py` re-measures and caches to `eval/sweep.json`; `--from
eval/sweep.json` replots without re-running retrieval. The λ heatmap sweeps
MMR's diversity parameter to test whether tuning could close the gap with
similarity — an open question this evaluation raises but does not yet answer.

Not generated, deliberately: training/validation curves (nothing is trained)
and ROC curves (the refusal decision is not threshold-based). See the README
for the reasoning.
