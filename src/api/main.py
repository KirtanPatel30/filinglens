"""FastAPI app: JSON + streaming endpoints, and serves the frontend.

Run locally:  uvicorn src.api.main:app --reload
"""
import json
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src import db
from src.agent.pipeline import answer, run
from src.config import FRONTEND_DIR, PipelineOptions, settings
from src.ingest.companies import COMPANIES

_status = {"models_ready": False, "warmup_error": None}


def _warm():
    try:
        from src.embeddings import warm_up

        warm_up()
        _status["models_ready"] = True
    except Exception as exc:  # the app still starts; /api/health reports the problem
        _status["warmup_error"] = str(exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    threading.Thread(target=_warm, daemon=True).start()
    yield


app = FastAPI(title="FilingLens", version="1.0.0", lifespan=lifespan)


class Options(BaseModel):
    use_bm25: bool | None = None
    use_rerank: bool | None = None
    use_agent: bool | None = None
    use_verify: bool | None = None


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    options: Options | None = None


def _opts(req: AskRequest) -> PipelineOptions:
    opts = PipelineOptions()
    if req.options:
        for k, v in req.options.model_dump().items():
            if v is not None:
                setattr(opts, k, v)
    return opts


@app.get("/api/health")
def health():
    model = {
        "ollama": settings.ollama_model,
        "anthropic": settings.anthropic_model,
        "openai": settings.openai_model,
    }.get(settings.llm_provider, settings.llm_provider)
    return {
        "status": "ok",
        "database": db.ping(),
        "models_ready": _status["models_ready"],
        "warmup_error": _status["warmup_error"],
        "llm_provider": settings.llm_provider,
        "llm_model": model,
    }


@app.get("/api/coverage")
def coverage():
    try:
        rows = db.coverage()
    except Exception as exc:
        raise HTTPException(503, f"Database unavailable: {exc}")
    return {
        "companies": [{"ticker": t, "name": c["name"]} for t, c in COMPANIES.items()],
        "filings": rows,
    }


@app.post("/api/ask")
def ask(req: AskRequest):
    return answer(req.question, _opts(req))


@app.post("/api/ask/stream")
def ask_stream(req: AskRequest):
    opts = _opts(req)

    def events():
        for ev in run(req.question, opts):
            yield f"data: {json.dumps(ev, default=str)}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")
