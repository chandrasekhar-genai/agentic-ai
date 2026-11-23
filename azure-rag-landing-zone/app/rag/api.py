from __future__ import annotations

from dataclasses import asdict

from fastapi import FastAPI
from pydantic import BaseModel, Field

from .config import Settings
from .pipeline import RagPipeline, build_pipeline


class ChatRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)


def create_app(pipeline: RagPipeline | None = None) -> FastAPI:
    settings = Settings()
    rag = pipeline or build_pipeline(settings)
    app = FastAPI(title="RAG API", version="0.1.0")

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok", "mode": settings.mode}

    @app.post("/chat")
    def chat(req: ChatRequest) -> dict:
        return asdict(rag.answer(req.question))

    return app
