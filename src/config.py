"""All settings live here and come from environment variables (or a .env file)."""
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
FRONTEND_DIR = ROOT / "frontend"


def _bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


@dataclass
class Settings:
    # --- database ---
    database_url: str = os.getenv(
        "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/filinglens"
    )

    # --- SEC download identity (required by SEC) ---
    sec_identity: str = os.getenv("SEC_IDENTITY", "")

    # --- embeddings / reranker ---
    embed_backend: str = os.getenv("EMBED_BACKEND", "fastembed")  # fastembed | hash
    embed_model: str = os.getenv("EMBED_MODEL", "BAAI/bge-small-en-v1.5")
    embed_dim: int = _int("EMBED_DIM", 384)
    rerank_model: str = os.getenv("RERANK_MODEL", "Xenova/ms-marco-MiniLM-L-6-v2")
    model_cache: str = os.getenv("MODEL_CACHE", str(ROOT / ".model_cache"))

    # --- LLM ---
    llm_provider: str = os.getenv("LLM_PROVIDER", "ollama")  # ollama | anthropic | openai | mock
    ollama_url: str = os.getenv("OLLAMA_URL", "http://localhost:11434")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_base_url: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    llm_timeout: float = _float("LLM_TIMEOUT", 120.0)

    # --- pipeline defaults (each can be switched off for ablations) ---
    use_bm25: bool = _bool("USE_BM25", True)
    use_rerank: bool = _bool("USE_RERANK", True)
    use_agent: bool = _bool("USE_AGENT", True)
    use_verify: bool = _bool("USE_VERIFY", True)

    candidates_per_retriever: int = _int("CANDIDATES_PER_RETRIEVER", 30)
    rerank_pool: int = _int("RERANK_POOL", 30)
    top_k: int = _int("TOP_K", 6)
    max_context_passages: int = _int("MAX_CONTEXT_PASSAGES", 10)
    max_retries: int = _int("MAX_RETRIES", 1)

    # Retry when the best passage looks weak. Rerank scores are 0..1 (sigmoid);
    # cosine is used when the reranker is off.
    retry_min_rerank: float = _float("RETRY_MIN_RERANK", 0.25)
    retry_min_cosine: float = _float("RETRY_MIN_COSINE", 0.62)
    # Below this, refuse without calling the LLM at all.
    refuse_below_rerank: float = _float("REFUSE_BELOW_RERANK", 0.02)

    # Verification: how similar a sentence must be to its cited evidence.
    support_threshold: float = _float("SUPPORT_THRESHOLD", 0.72)


settings = Settings()


@dataclass
class PipelineOptions:
    """Per-request switches. Used by the API and by the ablation eval."""

    use_bm25: bool = field(default_factory=lambda: settings.use_bm25)
    use_rerank: bool = field(default_factory=lambda: settings.use_rerank)
    use_agent: bool = field(default_factory=lambda: settings.use_agent)
    use_verify: bool = field(default_factory=lambda: settings.use_verify)
    top_k: int = field(default_factory=lambda: settings.top_k)
