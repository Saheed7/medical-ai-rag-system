"""Package the local FAISS index and publish it to S3 as a versioned artifact.

The index is a build artefact derived from a copyrighted corpus, so it is not
committed to Git. Instead this script uploads it to S3 and writes a manifest
(which IS committed) recording the version, checksum, and the configuration
that produced it. `fetch_index.py` uses that manifest to retrieve the exact
same bytes in CI.

Uses the AWS CLI via subprocess rather than boto3, so the only dependency is
an installed, configured `aws` binary - already present on the Jenkins agent.

Usage:
    python scripts/publish_index.py --bucket my-ml-artifacts --version v1
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
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import PROJECT_ROOT, settings  # noqa: E402

MANIFEST_PATH = PROJECT_ROOT / "vectorstore" / "INDEX_MANIFEST.json"
S3_PREFIX = "medical-ai-rag/index"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_aws_cli() -> None:
    if shutil.which("aws") is None:
        sys.exit(
            "The AWS CLI is not installed or not on PATH.\n"
            "Install it: https://aws.amazon.com/cli/  then run: aws configure"
        )


def read_vector_count() -> int:
    """Read the vector count without loading the embedding model."""
    try:
        import faiss  # noqa: PLC0415

        index = faiss.read_index(str(settings.vectorstore_dir / "index.faiss"))
        return int(index.ntotal)
    except Exception:  # noqa: BLE001
        return -1


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish the FAISS index to S3.")
    parser.add_argument("--bucket", required=True, help="Target S3 bucket name")
    parser.add_argument("--version", required=True, help="Artifact version, e.g. v1")
    parser.add_argument("--region", default=None, help="AWS region override")
    args = parser.parse_args()

    require_aws_cli()

    index_dir = settings.vectorstore_dir
    if not (index_dir / "index.faiss").exists():
        sys.exit(
            f"No index at {index_dir}.\n"
            "Build it first: python -m app.ingestion.build_index"
        )

    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "faiss_index.tar.gz"

        print(f"Packaging {index_dir} ...")
        with tarfile.open(archive, "w:gz") as tar:
            # arcname keeps the archive rooted at faiss_index/ regardless of
            # where it was built, so extraction is predictable.
            tar.add(index_dir, arcname="faiss_index")

        checksum = sha256_of(archive)
        size = archive.stat().st_size
        key = f"{S3_PREFIX}/{args.version}/faiss_index.tar.gz"
        uri = f"s3://{args.bucket}/{key}"

        print(f"  size    : {size / 1_048_576:.1f} MB")
        print(f"  sha256  : {checksum}")
        print(f"Uploading to {uri} ...")

        cmd = ["aws", "s3", "cp", str(archive), uri]
        if args.region:
            cmd += ["--region", args.region]

        result = subprocess.run(cmd, check=False)
        if result.returncode != 0:
            sys.exit("Upload failed. Check credentials with: aws sts get-caller-identity")

    manifest = {
        "version": args.version,
        "s3_uri": uri,
        "sha256": checksum,
        "size_bytes": size,
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "vectors": read_vector_count(),
        # Recording the producing configuration means a mismatch between the
        # index and the running app is detectable rather than silent.
        "embedding_model": settings.embedding_model_id,
        "chunk_size": settings.chunk_size,
        "chunk_overlap": settings.chunk_overlap,
    }

    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print(f"\nManifest written to {MANIFEST_PATH.relative_to(PROJECT_ROOT)}")
    print(json.dumps(manifest, indent=2))
    print("\nCommit the manifest so CI knows which index to fetch:")
    print("  git add vectorstore/INDEX_MANIFEST.json")
    print(f'  git commit -m "Publish FAISS index {args.version}"')


if __name__ == "__main__":
    main()
