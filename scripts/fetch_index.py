"""Fetch the FAISS index described by the committed manifest.

Run in CI before `docker build`. Downloads the exact artifact recorded in
vectorstore/INDEX_MANIFEST.json, verifies its SHA-256, and extracts it.

A checksum mismatch aborts the build: silently shipping a different index than
the one the manifest describes would make the deployment unreproducible.

Usage:
    python scripts/fetch_index.py
    python scripts/fetch_index.py --force     # re-download even if present
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import PROJECT_ROOT  # noqa: E402

MANIFEST_PATH = PROJECT_ROOT / "vectorstore" / "INDEX_MANIFEST.json"
TARGET_DIR = PROJECT_ROOT / "vectorstore" / "faiss_index"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch the FAISS index from S3.")
    parser.add_argument("--force", action="store_true", help="Re-download if present")
    parser.add_argument("--region", default=None, help="AWS region override")
    args = parser.parse_args()

    if not MANIFEST_PATH.exists():
        sys.exit(
            f"No manifest at {MANIFEST_PATH}.\n"
            "Publish an index first: python scripts/publish_index.py "
            "--bucket <bucket> --version v1"
        )

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    print(f"Manifest version : {manifest['version']}")
    print(f"Source           : {manifest['s3_uri']}")
    print(f"Expected sha256  : {manifest['sha256']}")

    if (TARGET_DIR / "index.faiss").exists() and not args.force:
        print(f"\nIndex already present at {TARGET_DIR}. Use --force to re-download.")
        return

    if shutil.which("aws") is None:
        sys.exit("The AWS CLI is not installed or not on PATH.")

    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "faiss_index.tar.gz"

        cmd = ["aws", "s3", "cp", manifest["s3_uri"], str(archive)]
        if args.region:
            cmd += ["--region", args.region]

        print(f"\nDownloading {manifest['s3_uri']} ...")
        if subprocess.run(cmd, check=False).returncode != 0:
            sys.exit("Download failed. Check AWS credentials and bucket permissions.")

        actual = sha256_of(archive)
        if actual != manifest["sha256"]:
            sys.exit(
                "CHECKSUM MISMATCH - aborting.\n"
                f"  expected {manifest['sha256']}\n"
                f"  actual   {actual}\n"
                "The S3 object differs from the manifest. Either the artifact was "
                "overwritten or the manifest is stale."
            )
        print("Checksum verified.")

        if TARGET_DIR.exists():
            shutil.rmtree(TARGET_DIR)
        TARGET_DIR.parent.mkdir(parents=True, exist_ok=True)

        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(TARGET_DIR.parent)  # noqa: S202 - artifact we produced

    if not (TARGET_DIR / "index.faiss").exists():
        sys.exit(f"Extraction did not produce {TARGET_DIR / 'index.faiss'}")

    print(f"Index ready at {TARGET_DIR}")


if __name__ == "__main__":
    main()
