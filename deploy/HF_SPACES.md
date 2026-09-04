# Public demo on Hugging Face Spaces

The Jenkins pipeline publishes the production image to a **private ECR
repository**. The public demo runs separately on Hugging Face Spaces, which
costs nothing and is appropriate for a portfolio deployment.

This split is deliberate rather than a workaround: ECR holds the deployable
artefact under access control, while the demo is a public, disposable instance.

---

## Why the index is not in the Space

The FAISS index contains verbatim text from the *Gale Encyclopedia of
Medicine*. Committing it to a public repository would publish a derived copy of
a copyrighted work — the same reason it is absent from GitHub.

The Space therefore fetches it at container startup from your private S3
bucket, verifies its SHA-256 against the committed manifest, and extracts it.
Only `INDEX_MANIFEST.json` (metadata: version, checksum, vector count,
chunking parameters) is public.

Serving short cited excerpts through a demo is a different act from
distributing the index itself.

---

## 1. Create the Space

1. Sign in at <https://huggingface.co> and go to <https://huggingface.co/new-space>
2. **Space name:** `medical-ai-rag-system`
3. **License:** MIT
4. **SDK:** **Docker** → **Blank**
5. **Hardware:** *CPU basic (2 vCPU, 16 GB)* — free
6. **Visibility:** Public
7. **Create Space**

You land on an empty repository with a git URL like
`https://huggingface.co/spaces/<your-username>/medical-ai-rag-system`.

---

## 2. Create a read-only S3 user for the Space

Do **not** reuse `medical-rag-dev`; it can write to S3 and, after the App
Runner detour, may still hold IAM permissions. The Space only needs to read one
object.

IAM → Users → **Create user** → `spaces-demo` → no console access →
**Attach policies directly** → `AmazonS3ReadOnlyAccess` → Create.

Then **Security credentials** → **Create access key** → *Application running
outside AWS*. Keep both values for step 4.

---

## 3. Populate the Space repository

Clone the Space alongside your project (not inside it):

```bash
cd C:/Projects
git clone https://huggingface.co/spaces/<your-username>/medical-ai-rag-system space-demo
cd space-demo
```

When git asks for a password, use a Hugging Face **access token** with *write*
permission from <https://huggingface.co/settings/tokens>, not your account
password.

Copy in what the Space needs:

```bash
cd C:/Projects/space-demo

# Application code and helper scripts
cp -r ../medical-ai-rag-system/app .
cp -r ../medical-ai-rag-system/scripts .

# Manifest only - never the index binaries
mkdir -p vectorstore
cp ../medical-ai-rag-system/vectorstore/INDEX_MANIFEST.json vectorstore/

# Dependencies and the Space-specific build
cp ../medical-ai-rag-system/requirements.txt .
cp ../medical-ai-rag-system/deploy/spaces/Dockerfile .
mkdir -p deploy/spaces
cp ../medical-ai-rag-system/deploy/spaces/entrypoint.sh deploy/spaces/

# The Space README carries the YAML front-matter that configures the Space
cp ../medical-ai-rag-system/deploy/spaces/README_SPACE.md README.md
```

Edit `README.md` and replace `Saheed7` in the GitHub link with your username.

Confirm no index binaries slipped in:

```bash
find . -name "index.faiss" -o -name "index.pkl"
```

That must print nothing. Then:

```bash
git add -A
git commit -m "Deploy Medical AI RAG System demo"
git push
```

The build starts automatically. Watch it under the **Logs** tab.

---

## 4. Add the secrets

In the Space: **Settings** → **Variables and secrets** → **New secret** for each.

| Name | Value |
|---|---|
| `HF_TOKEN` | your Hugging Face Inference token (from your local `.env`) |
| `AWS_ACCESS_KEY_ID` | the `spaces-demo` access key |
| `AWS_SECRET_ACCESS_KEY` | the `spaces-demo` secret |
| `AWS_REGION` | `us-east-1` |
| `LLM_REPO_ID` | `meta-llama/Llama-3.1-8B-Instruct` |
| `LLM_PROVIDER` | `novita` |

Use **Secrets** (encrypted, hidden after saving) for the three credentials.
The last three may be plain **Variables**.

Then **Settings** → **Factory rebuild**, so the container restarts with the
secrets present.

---

## 5. Verify

In the **Logs** tab you should see, in order:

```
Fetching index v1 from s3://medical-rag-artifacts-saheed7/... 
Checksum verified.
Index ready at /app/vectorstore/faiss_index (4932 vectors).
Starting Medical AI RAG System v1.0.0
FAISS index loaded (4932 vectors).
Initialising LLM endpoint: meta-llama/Llama-3.1-8B-Instruct (provider=novita)
RAG engine ready in ...
```

The first build takes 10–20 minutes (torch, sentence-transformers, the
embedding model). Later restarts are quick.

Then open the Space and ask a question. You want an answer with numbered
sources and page numbers.

---

## Troubleshooting

| Log message | Fix |
|---|---|
| `AWS credentials are not set` | Secrets missing or not applied — add them, then Factory rebuild |
| `Download failed: ClientError ... AccessDenied` | `spaces-demo` lacks S3 read, or wrong bucket region |
| `CHECKSUM MISMATCH` | The S3 object was replaced without republishing the manifest |
| `HF_TOKEN is not set` | Add `HF_TOKEN` as a secret |
| `404 ... router.huggingface.co` | Wrong `LLM_PROVIDER`; run `scripts/check_llm.py` locally |
| Build fails on torch | Free-tier disk pressure; retry, or drop to a smaller embedding model |

---

## Keeping it current

The Space has its own git remote, separate from GitHub. To ship changes:

```bash
cd C:/Projects/space-demo
cp -r ../medical-ai-rag-system/app .
git add -A && git commit -m "Sync application code" && git push
```

Free Spaces sleep after a period of inactivity and wake on the next request,
which adds a cold start of roughly a minute. That is acceptable for a demo; the
README explains the architecture for anyone who does not wait.

---

## Cost

| Item | Cost |
|---|---|
| Hugging Face Space (CPU basic) | free |
| S3 storage (8 MB) + occasional GET | pennies/month |
| ECR storage (~700 MB) | ~$0.07/month |

To remove everything later, see the cleanup commands in `deploy/APP_RUNNER.md`.
