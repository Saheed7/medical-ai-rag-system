#!/usr/bin/env bash
# Space container entrypoint: fetch the index, then start the app.
# Kept separate from the app so a fetch failure produces a clear message
# rather than an opaque startup error.
set -e
python scripts/bootstrap_index.py
exec python -m app.main
