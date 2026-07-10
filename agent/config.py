from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root (one level above agent/)
load_dotenv(Path(__file__).parent.parent / ".env")


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str
    anthropic_model: str
    anthropic_small_model: str  # cheap model for auxiliary work (history summarization)
    mcp_server_url: str


def load_settings() -> Settings:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY не найден. "
            "Создай файл .env в корне проекта и добавь строку:\n"
            "  ANTHROPIC_API_KEY=sk-ant-..."
        )
    return Settings(
        anthropic_api_key=api_key,
        anthropic_model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
        anthropic_small_model=os.environ.get(
            "ANTHROPIC_SMALL_MODEL", "claude-haiku-4-5-20251001"
        ),
        mcp_server_url=os.environ.get("MCP_SERVER_URL", "http://localhost:8000/mcp"),
    )


# Module-level singleton — fails fast at startup if key is missing.
settings: Settings = load_settings()
