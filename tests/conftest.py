"""Shared pytest fixtures."""

from __future__ import annotations

import pytest
from langchain_core.documents import Document


@pytest.fixture
def sample_documents() -> list[Document]:
    return [
        Document(
            page_content=(
                "Diabetes mellitus type 2 is a chronic metabolic disorder characterised "
                "by high blood glucose, insulin resistance, and relative insulin "
                "deficiency. Common symptoms include increased thirst, frequent "
                "urination, fatigue, and blurred vision. Risk factors include obesity, "
                "physical inactivity, and family history."
            ),
            metadata={"source": "gale.pdf", "page": 1042},
        ),
        Document(
            page_content=(
                "Iron deficiency anaemia occurs when the body lacks sufficient iron to "
                "produce haemoglobin. Causes include chronic blood loss, inadequate "
                "dietary intake, and impaired absorption. Symptoms range from fatigue "
                "and pallor to shortness of breath on exertion."
            ),
            metadata={"source": "gale.pdf", "page": 1873},
        ),
    ]
