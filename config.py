"""Shared settings. Set the API key and server URL in .env."""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env", override=False)

FIREBASE_API_KEY = os.getenv("FIREBASE_API_KEY", "").strip()
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "").strip().rstrip("/")
GUIDE_PATH = ROOT / "knowledge_base.json"
EMBED_MODEL = "embeddinggemma"
CHAT_MODEL = "qwen3:4b"
TOP_K = 3

