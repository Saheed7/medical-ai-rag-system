"""Pre-push safety check.

Verifies that no secrets, large binaries, or generated artefacts are about to
be committed. Run this BEFORE your first push - a token pushed to a public
repository is compromised the moment it lands, even if you delete it after.

Usage:
    python scripts/preflight_git.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Files that must never be tracked, whatever the .gitignore says.
FORBIDDEN_NAMES = {".env", "credentials.json", "id_rsa", ".aws"}
FORBIDDEN_SUFFIXES = {".pem", ".key", ".pfx", ".p12"}

# Credential shapes. Kept deliberately narrow to avoid false positives on
# ordinary prose and code.
SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("Hugging Face token", re.compile(r"\bhf_[A-Za-z0-9]{30,}\b")),
    ("AWS access key id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("AWS secret access key", re.compile(r"aws_secret_access_key\s*=\s*\S{20,}", re.I)),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("OpenAI key", re.compile(r"\bsk-[A-Za-z0-9]{32,}\b")),
    ("Private key block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("Generic hardcoded secret", re.compile(
        r"(?:password|passwd|secret|api_key|apikey|token)\s*=\s*[\"'][^\"'{$]{12,}[\"']",
        re.I,
    )),
]

MAX_FILE_MB = 5.0
TEXT_SUFFIXES = {
    ".py", ".txt", ".md", ".yml", ".yaml", ".json", ".toml", ".cfg",
    ".ini", ".sh", ".ps1", ".env", ".example", "", ".gitignore", ".dockerignore",
}


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
    )
    return result.stdout.strip()


def tracked_files() -> list[str]:
    out = git("ls-files")
    return [line for line in out.splitlines() if line]


def main() -> None:
    if not (ROOT / ".git").exists():
        print("No git repository here yet. Run 'git init' first.")
        sys.exit(1)

    files = tracked_files()
    if not files:
        print("No files staged or tracked yet. Run 'git add -A' first.")
        sys.exit(1)

    print(f"Checking {len(files)} tracked file(s)...\n")
    errors: list[str] = []
    warnings: list[str] = []

    for rel in files:
        path = ROOT / rel
        name = Path(rel).name

        if name in FORBIDDEN_NAMES or Path(rel).suffix in FORBIDDEN_SUFFIXES:
            errors.append(f"{rel}  -> credential file must not be tracked")
            continue

        if not path.exists():
            continue

        size_mb = path.stat().st_size / 1_048_576
        if size_mb > MAX_FILE_MB:
            warnings.append(f"{rel}  -> {size_mb:.1f} MB (large for a repo)")

        if Path(rel).suffix.lower() not in TEXT_SUFFIXES:
            continue

        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        for label, pattern in SECRET_PATTERNS:
            match = pattern.search(content)
            if not match:
                continue
            snippet = match.group(0)
            # Only the committed template may carry an obvious placeholder,
            # and only when the value is a recognised dummy. Matching on the
            # word "example" anywhere is too broad: the canonical AWS test key
            # contains it, and so would a real secret in an examples/ folder.
            placeholders = ("your_token_here", "xxxxx", "changeme", "<your", "placeholder")
            if rel == ".env.example" and any(ph in snippet.lower() for ph in placeholders):
                continue
            line_no = content[: match.start()].count("\n") + 1
            errors.append(f"{rel}:{line_no}  -> {label} detected")

    print("=" * 64)
    if errors:
        print("BLOCKED - do not push:\n")
        for e in errors:
            print(f"  ! {e}")
        print("\nRemove the file from tracking, then re-run:")
        print("  git rm --cached <file>")
        print("  echo <file> >> .gitignore")
    else:
        print("No secrets detected in tracked files.")

    if warnings:
        print("\nWarnings:")
        for w in warnings:
            print(f"  - {w}")

    # Confirm the ignore rules actually took effect.
    print("\n" + "=" * 64)
    print("Ignore-rule verification")
    print("=" * 64)
    for target in (".env", "vectorstore/faiss_index/index.faiss", "data/corpus.pdf"):
        ignored = bool(git("check-ignore", "-q", target) == "" and
                       subprocess.run(["git", "check-ignore", "-q", target],
                                      cwd=ROOT, check=False).returncode == 0)
        state = "ignored (good)" if ignored else "NOT IGNORED  <-- check .gitignore"
        print(f"  {target:<44} {state}")

    print()
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
