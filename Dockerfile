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
# setuptools is upgraded alongside pip: the base image ships 70.3.0, which
# carries CVE-2025-47273 (path traversal in PackageIndex) and vendors
# wheel 0.45.1 with CVE-2026-24049 (code execution via a malicious wheel).
# Both are flagged by the pipeline's Trivy gate.
RUN pip install --upgrade pip setuptools wheel && \
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

# The base image ships its own setuptools under /usr/local, separate from the
# venv. Its vendored copies of jaraco.context and wheel carry CVE-2026-23949
# and CVE-2026-24049. Upgrading in the builder stage does NOT fix this: PATH
# points at /opt/venv there, so pip only touches the venv's copy. The system
# interpreter must be targeted explicitly.
RUN /usr/local/bin/python -m pip install --no-cache-dir --upgrade \
        setuptools wheel && \
    rm -rf /root/.cache/pip

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /opt/hf-cache /opt/hf-cache

# pip is not needed at runtime: this container never installs packages. Removing
# it drops its vendored dependency tree, including the CycloneDX SBOM at
# pip/_vendor/bom.cdx.json. Trivy reads that manifest INSTEAD of the filesystem
# and reports msgpack 1.1.2 and setuptools 70.3.0 - neither of which is actually
# installed anywhere in this image. Deleting the code removes the finding at its
# source rather than suppressing the alert.
RUN /opt/venv/bin/python -m pip uninstall -y pip 2>/dev/null || true; \
    rm -rf /opt/venv/lib/python3.11/site-packages/pip \
           /opt/venv/lib/python3.11/site-packages/pip-*.dist-info \
           /usr/local/lib/python3.11/site-packages/pip \
           /usr/local/lib/python3.11/site-packages/pip-*.dist-info

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
