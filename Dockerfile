# syntax=docker/dockerfile:1.7
# =============================================================================
# Medical AI RAG System - production image
#
# Two-stage build:
#   builder  installs dependencies into an isolated virtualenv
#   runtime  copies only that virtualenv plus application code
#
# The compiler toolchain needed to build wheels never reaches the final image.
# =============================================================================

# -----------------------------------------------------------------------------
# Stage 1: builder
# -----------------------------------------------------------------------------
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# build-essential is required by some wheels; it stays in this stage only.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# CPU-only torch FIRST. sentence-transformers depends on torch, and the default
# PyPI wheel drags in ~3 GB of CUDA libraries that are useless on App Runner
# (no GPU). Installing the CPU build first means pip treats the dependency as
# already satisfied when it resolves the rest.
RUN pip install --upgrade pip && \
    pip install torch --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install -r requirements.txt

# Bake the embedding model into the image (~90 MB). Without this, every cold
# start downloads it from huggingface.co: slow, and a hard dependency on an
# external service at boot.
ENV HF_HOME=/opt/hf-cache
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"

# -----------------------------------------------------------------------------
# Stage 2: runtime
# -----------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    HF_HOME=/opt/hf-cache \
    HOST=0.0.0.0 \
    PORT=8080 \
    ENVIRONMENT=production

# Run as an unprivileged user. A container process that does not need root
# should never have it.
RUN groupadd --system --gid 1001 appgroup && \
    useradd --system --uid 1001 --gid appgroup --create-home appuser

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /opt/hf-cache /opt/hf-cache

WORKDIR /app

# Application code and the prebuilt FAISS index. The index is a build artefact
# produced by `python -m app.ingestion.build_index` on the developer machine.
COPY --chown=appuser:appgroup app/ ./app/
COPY --chown=appuser:appgroup vectorstore/ ./vectorstore/

RUN mkdir -p /app/logs && chown -R appuser:appgroup /app/logs /opt/hf-cache

USER appuser

EXPOSE 8080

# Uses the component-level /health endpoint. It returns 503 while the engine is
# degraded, so urlopen raises and the check correctly reports unhealthy.
HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health', timeout=5)" || exit 1

CMD ["python", "-m", "app.main"]
