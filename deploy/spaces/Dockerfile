# syntax=docker/dockerfile:1.7
# =============================================================================
# Hugging Face Spaces image.
#
# Differs from the root Dockerfile in three ways:
#   1. The FAISS index is NOT baked in. It is derived from a copyrighted corpus,
#      so it is fetched at startup from a private S3 bucket instead of being
#      distributed in a public image.
#   2. boto3 is installed for that fetch.
#   3. Runs as UID 1000, which is what Spaces expects for writable paths.
#
# Spaces builds this from the Space repository root, so paths are relative to
# a checkout that has this file at ./Dockerfile.
# =============================================================================

FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# CPU-only torch first: the default wheel pulls ~3 GB of unusable CUDA
# libraries. Spaces free tier has no GPU.
RUN pip install --upgrade pip setuptools wheel && \
    pip install torch --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install -r requirements.txt && pip install boto3

# Bake the embedding model so startup does not depend on huggingface.co.
ENV HF_HOME=/opt/hf-cache
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"

# -----------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    HF_HOME=/opt/hf-cache \
    HOST=0.0.0.0 \
    PORT=8080 \
    ENVIRONMENT=production

# Spaces runs containers as UID 1000; matching it avoids permission errors on
# any path the app writes to.
RUN useradd -m -u 1000 appuser

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /opt/hf-cache /opt/hf-cache

WORKDIR /app

COPY --chown=appuser:appuser app/ ./app/
COPY --chown=appuser:appuser scripts/ ./scripts/
COPY --chown=appuser:appuser vectorstore/INDEX_MANIFEST.json ./vectorstore/
COPY --chown=appuser:appuser deploy/spaces/entrypoint.sh ./entrypoint.sh

RUN chmod +x entrypoint.sh && \
    mkdir -p /app/logs /app/vectorstore && \
    chown -R appuser:appuser /app/logs /app/vectorstore /opt/hf-cache

USER appuser

EXPOSE 8080

CMD ["./entrypoint.sh"]
