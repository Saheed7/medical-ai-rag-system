# Screenshots

Place the following images here. Filenames must match the references in the
root `README.md`.

| Filename | What to capture |
|---|---|
| `demo-ui.png` | The Gradio interface mid-conversation, showing an answer with its numbered sources and page numbers |
| `jenkins-pipeline.png` | The Jenkins Stage View with all stages green, timings visible |
| `jenkins-trivy.png` | The Trivy summary in the build console, or the archived `trivy-summary.txt` |
| `docker-local.png` | Terminal showing `verify_docker.sh` at 16/0, or `docker images` with the size |
| `aws-ecr.png` | The ECR console listing the pushed image tags |
| `health-endpoint.png` | Browser or terminal showing the `/health` JSON response |

## Generated figures (do not screenshot these)

These are produced by scripts and committed as build outputs:

| Filename | Produced by |
|---|---|
| `retrieval_vs_k.png` | `python scripts/plot_eval.py` |
| `precision_recall.png` | `python scripts/plot_eval.py` |
| `mmr_lambda_heatmap.png` | `python scripts/plot_eval.py` (λ sweep) |
| `answerability_matrix.png` | `python scripts/evaluate_answerability.py --plot` |

Regenerate them after any change to chunking, the embedding model, or the
retrieval defaults — a figure that no longer matches the code is worse than no
figure.

Keep them under ~500 KB each; PNG at 1400px wide is plenty. Crop out anything
containing account identifiers you would rather not publish.
