"""Prompt templates and the medical-safety guardrail."""

from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate

SYSTEM_PROMPT = """You are a careful medical information assistant. You answer \
strictly from the reference excerpts supplied to you, which are drawn from the \
Gale Encyclopedia of Medicine.

Rules you must follow without exception:
1. Use ONLY the information in the provided context. Never rely on outside knowledge.
2. If the context does not contain the answer, reply exactly: \
"I could not find that information in the reference material."
3. Never invent drug names, dosages, numeric values, or clinical findings.
4. Be concise: 3-5 sentences unless the question demands a list.
5. Write for a general reader; expand medical jargon on first use.
6. You provide general information only, never diagnosis or treatment advice."""

USER_PROMPT = """Reference excerpts:
---------------------
{context}
---------------------

Question: {question}

Answer using only the excerpts above."""

# The exact string the model is instructed to emit when the corpus is silent.
NO_ANSWER_SENTINEL = "I could not find that information in the reference material."

MEDICAL_DISCLAIMER = (
    "This system provides general information retrieved from a medical reference text. "
    "It is not a medical device and does not provide diagnosis or treatment. "
    "Always consult a qualified healthcare professional. In an emergency, call your "
    "local emergency number."
)


def build_rag_prompt() -> ChatPromptTemplate:
    """Return the chat prompt used for grounded question answering."""
    return ChatPromptTemplate.from_messages(
        [("system", SYSTEM_PROMPT), ("human", USER_PROMPT)]
    )
