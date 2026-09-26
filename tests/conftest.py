import os

# Tests never download models or call a real LLM.
os.environ.setdefault("EMBED_BACKEND", "hash")
os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("SUPPORT_THRESHOLD", "0.5")
