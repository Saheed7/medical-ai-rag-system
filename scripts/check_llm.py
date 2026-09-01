"""Discover which Hugging Face inference providers actually serve your model,
then send a live test request.

Hugging Face routes chat requests through third-party providers. A model that
exists on the Hub is NOT necessarily served by the provider HF picks for you,
which surfaces as a confusing 404 from a router URL such as
    https://router.huggingface.co/<provider>/v3/openai/chat/completions

Usage:
    python scripts/check_llm.py                       # check configured model
    python scripts/check_llm.py meta-llama/Llama-3.1-8B-Instruct
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402

# Reliable, widely-served instruct models to fall back on, in preference order.
CANDIDATES = [
    "meta-llama/Llama-3.1-8B-Instruct",
    "Qwen/Qwen2.5-7B-Instruct",
    "mistralai/Mistral-7B-Instruct-v0.3",
    "meta-llama/Llama-3.3-70B-Instruct",
    "microsoft/Phi-3.5-mini-instruct",
]


def banner(t: str) -> None:
    print(f"\n{'=' * 66}\n{t}\n{'=' * 66}")


def providers_for(repo_id: str, token: str) -> list[str]:
    """Return provider names that serve `repo_id`, live from the Hub API."""
    from huggingface_hub import HfApi

    try:
        info = HfApi(token=token).model_info(
            repo_id, expand=["inferenceProviderMapping"]
        )
    except Exception as exc:  # noqa: BLE001
        print(f"  could not query Hub: {type(exc).__name__}: {exc}")
        return []

    mapping = getattr(info, "inference_provider_mapping", None) or []

    names: list[str] = []
    for entry in mapping:
        name = getattr(entry, "provider", None) or (
            entry.get("provider") if isinstance(entry, dict) else None
        )
        status = getattr(entry, "status", None) or (
            entry.get("status") if isinstance(entry, dict) else None
        )
        if name and status != "error":
            names.append(name)
    return sorted(set(names))


def live_test(repo_id: str, provider: str, token: str) -> bool:
    """Send one real chat request. Returns True on success."""
    from huggingface_hub import InferenceClient

    try:
        client = InferenceClient(provider=provider, api_key=token, timeout=60)
        out = client.chat_completion(
            model=repo_id,
            messages=[{"role": "user", "content": "Reply with the single word: ready"}],
            max_tokens=10,
        )
        print(f"    OK  <- {out.choices[0].message.content.strip()[:40]!r}")
        return True
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).split("\n")[0][:110]
        print(f"    FAIL  {type(exc).__name__}: {msg}")
        return False


def main() -> None:
    token = settings.hf_token
    if not token:
        print("HF_TOKEN is not set. Run: python scripts/check_env.py")
        sys.exit(1)

    target = sys.argv[1] if len(sys.argv) > 1 else settings.llm_repo_id

    banner(f"1. PROVIDERS SERVING  {target}")
    available = providers_for(target, token)
    if available:
        for name in available:
            print(f"  - {name}")
    else:
        print("  none reported (model may be gated, private, or unserved)")

    banner("2. LIVE REQUEST TEST")
    working: list[tuple[str, str]] = []
    for provider in available:
        print(f"  {target} via {provider}:")
        if live_test(target, provider, token):
            working.append((target, provider))

    if not working:
        banner("3. TRYING FALLBACK MODELS")
        for candidate in CANDIDATES:
            if candidate == target:
                continue
            provs = providers_for(candidate, token)
            if not provs:
                continue
            for provider in provs[:2]:
                print(f"  {candidate} via {provider}:")
                if live_test(candidate, provider, token):
                    working.append((candidate, provider))
                    break
            if working:
                break

    banner("RESULT")
    if working:
        model, provider = working[0]
        print("  A working combination was found. Put these in your .env:\n")
        print(f"    LLM_REPO_ID={model}")
        print(f"    LLM_PROVIDER={provider}\n")
        print("  Then restart:  python -m app.main")
    else:
        print("  No working model/provider combination found.")
        print("  Likely causes:")
        print("    1. Your token lacks 'Make calls to Inference Providers'")
        print("       permission. Edit it at huggingface.co/settings/tokens")
        print("    2. The models are gated - accept terms on each model page.")
        print("    3. Your free monthly inference credits are exhausted.")
        print("\n  Browse servable models at:")
        print("    https://huggingface.co/models?inference_provider=all&pipeline_tag=text-generation")


if __name__ == "__main__":
    main()
