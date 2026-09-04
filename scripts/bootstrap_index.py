"""Download the FAISS index from private S3 at container startup.

Used by the Hugging Face Spaces deployment. The index is derived from a
copyrighted corpus, so it is never committed to a public repository or baked
into a publicly distributed image. It is fetched at runtime from a private
bucket using credentials supplied as Space secrets, verified against the
committed manifest, and extracted.

If the index is already present (for example in a locally built image), this
is a no-op.

Usage:
    python scripts/bootstrap_index.py
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
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


def parse_s3_uri(uri: str) -> tuple[str, str]:
    if not uri.startswith("s3://"):
        raise ValueError(f"Not an S3 URI: {uri}")
    bucket, _, key = uri[5:].partition("/")
    return bucket, key


def main() -> None:
    if (TARGET_DIR / "index.faiss").exists():
        print(f"Index already present at {TARGET_DIR}; nothing to do.")
        return

    if not MANIFEST_PATH.exists():
        sys.exit(f"No manifest at {MANIFEST_PATH}. Cannot locate the index artifact.")

    try:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        sys.exit(f"Manifest is not valid JSON: {exc}")

    try:
        bucket, key = parse_s3_uri(manifest["s3_uri"])
    except (KeyError, ValueError) as exc:
        sys.exit(f"Manifest does not contain a usable s3_uri: {exc}")
    region = os.environ.get("AWS_REGION", "us-east-1")

    print(f"Fetching index {manifest['version']} from s3://{bucket}/{key} ...")

    try:
        import boto3  # noqa: PLC0415
    except ImportError:
        sys.exit("boto3 is not installed. Add it to the deployment image.")

    if not os.environ.get("AWS_ACCESS_KEY_ID"):
        sys.exit(
            "AWS credentials are not set. In the Space, add AWS_ACCESS_KEY_ID and "
            "AWS_SECRET_ACCESS_KEY under Settings -> Variables and secrets."
        )

    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "faiss_index.tar.gz"
        try:
            boto3.client("s3", region_name=region).download_file(
                bucket, key, str(archive)
            )
        except Exception as exc:  # noqa: BLE001
            sys.exit(f"Download failed: {type(exc).__name__}: {exc}")

        actual = sha256_of(archive)
        if actual != manifest["sha256"]:
            sys.exit(
                "CHECKSUM MISMATCH - refusing to start.\n"
                f"  expected {manifest['sha256']}\n  actual   {actual}"
            )
        print("Checksum verified.")

        if TARGET_DIR.exists():
            shutil.rmtree(TARGET_DIR)
        TARGET_DIR.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(TARGET_DIR.parent)  # noqa: S202 - artifact we produced

    if not (TARGET_DIR / "index.faiss").exists():
        sys.exit("Extraction did not produce index.faiss")

    print(f"Index ready at {TARGET_DIR} ({manifest['vectors']} vectors).")


if __name__ == "__main__":
    main()
