"""Gradio chat interface for the Medical AI RAG System."""

from __future__ import annotations

import gradio as gr

from app.core.config import settings
from app.core.exceptions import ConfigurationError, MedicalRAGError, VectorStoreError
from app.core.logger import get_logger
from app.rag.engine import RAGResponse, get_engine
from app.rag.prompts import MEDICAL_DISCLAIMER

logger = get_logger(__name__)

# Gradio 6 renders examples inside the Chatbot itself, as dicts with a
# "text" key, rather than through a separate gr.Examples block.
EXAMPLE_QUESTIONS = [
    "What are the common symptoms of Type 2 diabetes?",
    "How is bacterial meningitis diagnosed?",
    "What causes iron deficiency anaemia?",
    "Explain the difference between Crohn's disease and ulcerative colitis.",
    "What are the risk factors for deep vein thrombosis?",
]

CUSTOM_CSS = """
.disclaimer-box {
    border-left: 4px solid #d97706;
    background: rgba(217, 119, 6, 0.08);
    padding: 12px 16px;
    border-radius: 6px;
    font-size: 0.88rem;
    line-height: 1.5;
}
footer { visibility: hidden; }
"""


def _render(response: RAGResponse) -> str:
    """Turn a RAGResponse into the markdown shown in the chat bubble."""
    parts = [response.answer]

    if response.has_citations:
        parts.append("\n---\n**Sources**")
        for i, citation in enumerate(response.citations, start=1):
            parts.append(f"{i}. {citation.render()}")

    parts.append(f"\n<sub>Answered in {response.latency_ms:.0f} ms</sub>")
    return "\n".join(parts)


def _friendly_error(exc: Exception) -> str:
    """Map internal failures to actionable user-facing text."""
    if isinstance(exc, VectorStoreError):
        return (
            "**The knowledge index is not available.**\n\n"
            "Build it first:\n```bash\npython -m app.ingestion.build_index\n```"
        )
    if isinstance(exc, ConfigurationError):
        return (
            "**Configuration problem.**\n\n"
            "`HF_TOKEN` appears to be missing. Copy `.env.example` to `.env` "
            "and add your Hugging Face token."
        )
    if isinstance(exc, MedicalRAGError):
        return f"**Something went wrong.**\n\n`{exc.message}`"
    return "**An unexpected error occurred.** Please check the application logs."


def respond(message: str, history: list[dict]) -> tuple[str, list[dict]]:
    """Gradio callback: append the user turn and the assistant turn."""
    if not message or not message.strip():
        return "", history

    history = history + [{"role": "user", "content": message}]

    try:
        response = get_engine().answer(message)
        reply = _render(response)
    except Exception as exc:  # noqa: BLE001 - never crash the UI thread
        logger.exception("Failed to answer question: %s", message[:120])
        reply = _friendly_error(exc)

    history = history + [{"role": "assistant", "content": reply}]
    return "", history


def build_interface() -> gr.Blocks:
    """Construct the Gradio Blocks application."""
    # Gradio 6 moved `theme` and `css` off the Blocks constructor; they are
    # now passed to launch() or mount_gradio_app(). See app/main.py.
    with gr.Blocks(title=settings.app_name, fill_height=True) as demo:

        gr.Markdown(f"# {settings.app_name}")
        gr.Markdown(
            "Retrieval-augmented question answering over the "
            "*Gale Encyclopedia of Medicine*. Every answer is grounded in "
            "retrieved passages and shown with page-level citations."
        )
        gr.Markdown(
            f'<div class="disclaimer-box">⚕️ <strong>Disclaimer.</strong> '
            f"{MEDICAL_DISCLAIMER}</div>"
        )

        # Gradio 6 dropped `type`: the messages format is now the only one.
        # `show_copy_button` was replaced by the `buttons` list, and examples
        # are rendered by the Chatbot itself when it is empty.
        chatbot = gr.Chatbot(
            height=520,
            label="Conversation",
            avatar_images=(None, None),
            buttons=["copy"],
            examples=[{"text": q} for q in EXAMPLE_QUESTIONS],
        )

        with gr.Row():
            textbox = gr.Textbox(
                placeholder="Ask a medical question...",
                show_label=False,
                scale=9,
                autofocus=True,
                max_lines=4,
            )
            submit_btn = gr.Button("Send", variant="primary", scale=1)

        with gr.Row():
            clear_btn = gr.Button("Clear conversation", size="sm")

        with gr.Accordion("System configuration", open=False):
            gr.Markdown(
                f"""
| Component | Value |
|---|---|
| Version | `{settings.app_version}` |
| Environment | `{settings.environment}` |
| Embedding model | `{settings.embedding_model_id}` |
| LLM | `{settings.llm_repo_id}` |
| Retrieval | `{settings.retrieval_strategy}`, top-k = `{settings.retrieval_top_k}` |
| Chunking | size `{settings.chunk_size}`, overlap `{settings.chunk_overlap}` |
"""
            )

        # Wiring
        def _from_example(evt: gr.SelectData, history: list[dict]):
            """Chatbot examples emit a select event rather than filling the box."""
            text = evt.value.get("text", "") if isinstance(evt.value, dict) else str(evt.value)
            return respond(text, history)

        chatbot.example_select(_from_example, [chatbot], [textbox, chatbot])
        textbox.submit(respond, [textbox, chatbot], [textbox, chatbot])
        submit_btn.click(respond, [textbox, chatbot], [textbox, chatbot])
        clear_btn.click(lambda: [], outputs=chatbot, queue=False)

    return demo
