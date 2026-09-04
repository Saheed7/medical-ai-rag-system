---
title: Medical AI RAG System
emoji: 🩺
colorFrom: teal
colorTo: blue
sdk: docker
app_port: 8080
pinned: false
license: mit
---

# Medical AI RAG System

Retrieval-augmented question answering over a medical reference corpus, with
page-level citations on every answer.

Ask a medical question and the system retrieves relevant passages from an
indexed encyclopaedia, then answers **only** from those passages — showing you
the exact sources and page numbers it used. If the corpus does not contain an
answer, it says so rather than inventing one.

**Source code and full engineering write-up:**
https://github.com/Saheed7/medical-ai-rag-system

## How it works

```
question → MMR retrieval (k=4, FAISS) → grounded prompt → Llama-3.1-8B → answer + citations
```

- **Embeddings:** `sentence-transformers/all-MiniLM-L6-v2`, 4,932 indexed vectors
- **Vector search:** FAISS with maximal marginal relevance
- **Generation:** Llama-3.1-8B-Instruct via Hugging Face Inference Providers
- **Interface:** Gradio 5 mounted on FastAPI, with a component-level `/health` endpoint

The retrieval index is a build artefact fetched from private object storage at
startup and verified by SHA-256 against a committed manifest, so this public
image contains no corpus text.

## Disclaimer

This provides **general information** from a reference text. It is **not a
medical device** and does not provide diagnosis or treatment. Always consult a
qualified healthcare professional. In an emergency, call your local emergency
number.
