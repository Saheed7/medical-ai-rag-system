"""Application entrypoint.

Serves the Gradio UI mounted on a FastAPI app, so container orchestrators
(Docker, AWS App Runner) get a real HTTP health endpoint that is separate
from the UI route.

Run locally:  python -m app.main
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import gradio as gr
import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.logger import get_logger
from app.rag.engine import get_engine
from app.ui.gradio_app import CUSTOM_CSS, build_interface

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Warm the engine at boot so the first user request isn't slow."""
    logger.info("Starting %s v%s", settings.app_name, settings.app_version)
    try:
        get_engine().warm_up()
    except Exception:  # noqa: BLE001
        # Log and continue. The UI renders an actionable error instead of the
        # container crash-looping before anyone can read the message.
        logger.exception("Engine warm-up failed; the UI will surface the error.")
    yield
    logger.info("Shutting down.")


api = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/api/docs",
)


@api.get("/health", tags=["ops"])
def health() -> JSONResponse:
    """Readiness probe consumed by Docker HEALTHCHECK and AWS App Runner."""
    engine = get_engine()
    payload = engine.health()
    return JSONResponse(content=payload, status_code=200 if engine.is_ready else 503)


# Gradio 6 accepts theme and css here rather than on the Blocks constructor.
app = gr.mount_gradio_app(
    api,
    build_interface(),
    path="/",
    theme=gr.themes.Soft(primary_hue="teal", secondary_hue="slate"),
    css=CUSTOM_CSS,
)


def main() -> None:
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        workers=1,  # single worker: FAISS index and models live in-process
    )


if __name__ == "__main__":
    main()
