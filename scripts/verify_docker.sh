#!/usr/bin/env bash
# Staged verification of the container image.
#
# NOTE ON GIT BASH / MSYS2 (Windows):
# MSYS rewrites arguments that look like absolute Unix paths into Windows
# paths before the child process sees them, so
#     docker run IMG test -f /app/x
# silently becomes
#     docker run IMG test -f C:/Program Files/Git/app/x
# Every in-container path below is therefore wrapped inside `sh -c '...'`,
# where it is an ordinary string rather than an argument, and MSYS_NO_PATHCONV
# is set as a second line of defence.
set -uo pipefail
export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL="*"

IMAGE="${1:-medical-ai-rag-system:latest}"
pass=0; fail=0

check() {
  local label="$1"; shift
  if "$@" >/dev/null 2>&1; then
    echo "  PASS  $label"; pass=$((pass+1))
  else
    echo "  FAIL  $label"; fail=$((fail+1))
  fi
}

# Run a shell snippet inside the image. Paths stay inside the quoted string.
in_image() { docker run --rm "$IMAGE" sh -c "$1"; }

echo "=============================================================="
echo "1. PREREQUISITES"
echo "=============================================================="
check "docker daemon reachable"       docker info
check "prebuilt FAISS index present"  test -f vectorstore/faiss_index/index.faiss
check ".env present"                  test -f .env

echo
echo "=============================================================="
echo "2. IMAGE"
echo "=============================================================="
if docker image inspect "$IMAGE" >/dev/null 2>&1; then
  size=$(docker image inspect "$IMAGE" --format '{{.Size}}')
  echo "  image size: $(( size / 1048576 )) MB"
  if [ "$size" -lt 2500000000 ]; then
    echo "  PASS  under 2.5 GB"; pass=$((pass+1))
  else
    echo "  WARN  larger than expected - is CPU-only torch installed?"
  fi
else
  echo "  FAIL  image '$IMAGE' not found - run: docker build -t $IMAGE ."
  fail=$((fail+1))
fi

echo
echo "=============================================================="
echo "3. IMAGE CONTENTS"
echo "=============================================================="
check "runs as non-root (uid 1001)" \
  sh -c "[ \"\$(docker run --rm $IMAGE id -u)\" = '1001' ]"
check "FAISS index baked in" \
  in_image 'test -f /app/vectorstore/faiss_index/index.faiss'
check "FAISS docstore baked in" \
  in_image 'test -f /app/vectorstore/faiss_index/index.pkl'
check "embedding model cached" \
  in_image 'find /opt/hf-cache -name "*.safetensors" -o -name "pytorch_model.bin" | grep -q .'
check "no .env in image" \
  in_image '! test -f /app/.env'
check "no source PDF in image" \
  in_image '! find / -name "*.pdf" -not -path "/proc/*" 2>/dev/null | grep -q .'
# Every torch build ships torch/cuda/ - torch.cuda.is_available() must exist
# in order to return False - so matching on "*cuda*" gives a false failure.
# The real weight is the separate nvidia-* packages (cuBLAS, cuDNN, NCCL),
# which the CPU wheel does not pull in.
check "no nvidia CUDA runtime packages" \
  in_image '! ls -d /opt/venv/lib/python*/site-packages/nvidia 2>/dev/null | grep -q .'
check "no bundled CUDA shared objects" \
  in_image '! find /opt/venv -name "libcudnn*" -o -name "libcublas*" -o -name "libnccl*" | grep -q .'
check "torch is a +cpu build" \
  in_image 'python -c "import torch,sys; sys.exit(0 if \"+cpu\" in torch.__version__ else 1)"' 

echo "  torch build: $(in_image 'python -c "import torch; print(torch.__version__)"' 2>/dev/null || echo unknown)"

echo
echo "=============================================================="
echo "4. RUNTIME"
echo "=============================================================="
echo "  starting container..."
docker rm -f medical-rag-verify >/dev/null 2>&1
if docker run -d --name medical-rag-verify --env-file .env -p 8099:8080 "$IMAGE" >/dev/null 2>&1; then
  body=""
  for _ in $(seq 1 30); do
    body=$(curl -fsS http://localhost:8099/health 2>/dev/null) && break
    sleep 3
  done
  if [ -n "$body" ]; then
    echo "  PASS  /health responded"; pass=$((pass+1))
    echo "  $body"
    for field in '"retriever_ready":true' '"llm_ready":true'; do
      compact=$(echo "$body" | tr -d ' ')
      if echo "$compact" | grep -q "$field"; then
        echo "  PASS  ${field%%:*} true"; pass=$((pass+1))
      else
        echo "  WARN  ${field%%:*} not true - check HF_TOKEN / LLM_PROVIDER"
      fi
    done
    # The image sets ENVIRONMENT=production, but --env-file .env overrides it.
    if echo "$body" | tr -d ' ' | grep -q '"environment":"development"'; then
      echo "  NOTE  reporting 'development': your .env overrides the image default."
      echo "        Harmless locally; App Runner will set production explicitly."
    fi
  else
    echo "  FAIL  /health never responded"; fail=$((fail+1))
    echo "  --- container logs ---"
    docker logs medical-rag-verify 2>&1 | tail -25
  fi
  docker rm -f medical-rag-verify >/dev/null 2>&1
else
  echo "  FAIL  container would not start"; fail=$((fail+1))
fi

echo
echo "=============================================================="
echo "  passed: $pass   failed: $fail"
echo "=============================================================="
[ "$fail" -eq 0 ]
