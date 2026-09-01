# Medical AI RAG System

A production-oriented **Retrieval-Augmented Generation (RAG)** service that answers
medical questions strictly from an indexed reference corpus (*The Gale Encyclopedia
of Medicine*, 2nd ed.), returning **page-level citations** with every answer.

Built to demonstrate end-to-end ML engineering: document ingestion, vector
retrieval, grounded generation, containerisation, automated security scanning,
CI/CD, and cloud deployment.

---

## Why this exists

General-purpose LLMs hallucinate confidently on medical questions. This system
constrains the model to a curated corpus and makes every claim auditable: the
answer is accompanied by the exact source passages and page numbers it was
derived from. If the corpus does not contain an answer, the system says so
rather than inventing one.

---

## Architecture

```
                 ┌──────────────────── INGESTION (offline, one-shot) ─────────────────────┐
                 │                                                                        │
  data/*.pdf ──► PyPDFLoader ──► text cleaning ──► recursive chunking ──► MiniLM embed ──► FAISS index
                 │              (de-hyphenate,      (800 chars,            (384-dim,        (persisted
                 │               strip headers)      120 overlap)          normalised)      to disk)
                 └────────────────────────────────────────────────────────────────────────┘

                 ┌──────────────────── SERVING (online, per request) ─────────────────────┐
                 │                                                                        │
  user question ──► MMR retrieval (k=4) ──► prompt assembly ──► Mistral-7B ──► grounded answer
                 │        from FAISS          (system rules +      via HF       + citations
                 │                             numbered excerpts)  Inference API
                 └────────────────────────────────────────────────────────────────────────┘

  Gradio UI  ⇄  FastAPI (mounts Gradio at /, exposes /health for probes)
```

### Design decisions

| Decision | Rationale |
|---|---|
| **Singleton engine, warmed at startup** | Embedding model (~90 MB) and FAISS index load once per process, not per request. First-request latency moves to boot time. |
| **MMR retrieval over pure similarity** | Encyclopaedia entries span consecutive pages; plain top-k returns near-duplicate chunks. MMR (`fetch_k=20`, `λ=0.5`) diversifies the context window. |
| **800-char chunks / 120 overlap** | Large enough to hold a complete symptom list or definition; overlap prevents facts being severed at a boundary. |
| **Normalised embeddings** | Lets FAISS inner-product search act as cosine similarity without a separate normalisation pass. |
| **Explicit no-answer sentinel** | The prompt defines an exact refusal string; the engine detects it and suppresses citations, so the UI never shows sources for a non-answer. |
| **Typed exception hierarchy** | A missing index and an LLM timeout are different failures with different fixes. The UI maps each to actionable guidance. |
| **FastAPI wrapper around Gradio** | Gives a real `/health` endpoint for Docker `HEALTHCHECK` and AWS App Runner, independent of the UI route. |

---

## Tech stack

| Layer | Technology |
|---|---|
| Orchestration | LangChain (LCEL) |
| Embeddings | `sentence-transformers/all-MiniLM-L6-v2` |
| Vector store | FAISS (CPU) |
| LLM | `mistralai/Mistral-7B-Instruct-v0.3` via Hugging Face Inference API |
| UI | Gradio 5 |
| Web server | FastAPI + Uvicorn |
| Config | pydantic-settings |
| Testing | pytest |
| Container | Docker |
| CI/CD | Jenkins |
| Security scan | Aqua Trivy |
| Registry | AWS ECR |
| Runtime | AWS App Runner |

---

## Project layout

```
medical-ai-rag-system/
├── app/
│   ├── core/            # config, logging, typed exceptions
│   │   ├── config.py
│   │   ├── exceptions.py
│   │   └── logger.py
│   ├── ingestion/       # offline pipeline: PDF → chunks → index
│   │   ├── pdf_loader.py
│   │   ├── chunker.py
│   │   └── build_index.py
│   ├── rag/             # online pipeline: retrieve → generate
│   │   ├── embeddings.py
│   │   ├── vector_store.py
│   │   ├── llm.py
│   │   ├── prompts.py
│   │   └── engine.py
│   ├── ui/
│   │   └── gradio_app.py
│   └── main.py          # FastAPI + Gradio entrypoint
├── data/                # source PDFs
├── vectorstore/         # generated FAISS index (gitignored)
├── tests/
├── deploy/jenkins/      # custom Jenkins image (Docker-in-Docker)
├── Dockerfile
├── Jenkinsfile
├── requirements.txt
└── Makefile
```

---

## Quickstart

**Prerequisites:** Python 3.10+, a free [Hugging Face token](https://huggingface.co/settings/tokens).

```bash
# 1. Clone and enter
git clone https://github.com/<your-username>/medical-ai-rag-system.git
cd medical-ai-rag-system

# 2. Virtual environment
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 3. Dependencies
pip install -r requirements.txt

# 4. Configure
cp .env.example .env               # Windows: copy .env.example .env
# then edit .env and set HF_TOKEN=hf_...

# 5. Add the corpus (see "Source corpus" below)
#    Place the reference PDF into data/

# 6. Build the vector index (one-off, ~10-25 min for the full encyclopaedia)
python -m app.ingestion.build_index

# 7. Run
python -m app.main
```

Open <http://localhost:8080>. Health probe at <http://localhost:8080/health>.

### Make targets

```bash
make install-dev    # runtime + dev dependencies
make index          # rebuild the FAISS index
make run            # start the app
make test           # pytest with coverage
make lint           # ruff
```

---

## Source corpus

The system indexes *The Gale Encyclopedia of Medicine* (2nd ed.), a copyrighted
commercial reference work. It is **not** redistributed in this repository. To
run the system, place your own copy at `data/<name>.pdf` — the loader picks up
any PDF in that directory, so the filename does not matter.

Verify the file before the long index build:

```bash
python scripts/diagnose_pdf.py
```

This checks file integrity, raw text extraction, the loader, and the cleaning
pass, reporting which stage loses the text. A truncated PDF still reports the
correct page count but yields no extractable text, which is otherwise a
baffling failure.

---

## Configuration

Every setting is overridable via `.env` or environment variables.

| Variable | Default | Purpose |
|---|---|---|
| `HF_TOKEN` | *(required)* | Hugging Face Inference API token |
| `PORT` | `8080` | HTTP listen port |
| `ENVIRONMENT` | `development` | `development` / `production` |
| `LOG_LEVEL` | `INFO` | Root log level |
| `CHUNK_SIZE` | `800` | Characters per chunk |
| `CHUNK_OVERLAP` | `120` | Overlap between chunks |
| `RETRIEVAL_TOP_K` | `4` | Chunks passed to the LLM |
| `RETRIEVAL_STRATEGY` | `mmr` | `mmr` or `similarity` |
| `LLM_REPO_ID` | `meta-llama/Llama-3.1-8B-Instruct` | Generation model |
| `LLM_PROVIDER` | `auto` | Hugging Face inference provider |
| `EMBEDDING_MODEL_ID` | `sentence-transformers/all-MiniLM-L6-v2` | Embedding model |

Configuration is validated at import time (`chunk_overlap < chunk_size`,
`retrieval_strategy ∈ {mmr, similarity}`), so misconfiguration fails at boot
rather than mid-request.

---

## Testing

```bash
pytest -v --cov=app --cov-report=term-missing
```

Covers configuration validation, PDF text-cleaning heuristics, chunking
invariants (sequential IDs, metadata preservation), prompt contracts, and
citation formatting.

---

## Troubleshooting

Three diagnostic scripts cover the failure modes worth having tooling for.

| Symptom | Run | What it checks |
|---|---|---|
| `no extractable text was found` | `python scripts/diagnose_pdf.py` | File integrity, raw extraction, loader, cleaning — per stage |
| `HF_TOKEN is not set` | `python scripts/check_env.py` | `.env` existence, BOM, token shape, shell override |
| `404 ... router.huggingface.co/<provider>/...` | `python scripts/check_llm.py` | Which providers serve your model; sends a live test request |

### On the 404

Hugging Face routes chat requests through third-party inference providers. A
model can exist on the Hub yet not be served by the provider HF selects for
you, which surfaces as a 404 from a router URL. `check_llm.py` queries the Hub
for the actual provider mapping, tests each with a real request, and prints the
`LLM_REPO_ID` / `LLM_PROVIDER` pair to put in `.env`.

Pin the provider explicitly rather than relying on `auto`. Provider coverage
shifts over time, and an implicit choice is not reproducible across
environments — including inside a container.

If every model fails, check that your token has **"Make calls to Inference
Providers"** enabled at <https://huggingface.co/settings/tokens>. Fine-grained
tokens do not grant it by default. Gated models (Llama, Mistral) additionally
require accepting terms on the model page.

### Health endpoint

`/health` reports component-level readiness rather than a single boolean:

```json
{"status": "degraded", "retriever_ready": true, "llm_ready": false, "vectors": 4932}
```

This distinguishes a retrieval failure from a generation failure, which is the
distinction that matters when diagnosing a live system.

---

## Disclaimer

This system provides **general information** retrieved from a medical reference
text. It is **not a medical device** and does not provide diagnosis or treatment.
Always consult a qualified healthcare professional. In an emergency, call your
local emergency number.

---

## Licence

MIT — see [LICENSE](LICENSE).

The Gale Encyclopedia of Medicine is used here solely as a demonstration corpus
and is not redistributed under this licence.
