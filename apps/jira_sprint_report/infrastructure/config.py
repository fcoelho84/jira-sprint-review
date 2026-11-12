from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from jira_sprint_report.domain.models import Settings

ROOT = Path(__file__).resolve().parents[3]
APPS_DIR = ROOT / "apps"
WEB_DIR = APPS_DIR / "web"
PROMPTS_DIR = ROOT / "prompts"
OUTPUT_DIR = ROOT / "output"
ENV_PATH = ROOT / ".env"
COOKIES_PATH = ROOT / ".cookies.json"
STORAGE_STATE_PATH = ROOT / ".storage_state.json"
BROWSER_PROFILE_DIR = ROOT / ".browser-profile"
PLAYWRIGHT_BROWSERS_DIR = ROOT / ".playwright-browsers"


def _cookie_from_disk() -> str:
    try:
        from jira_sprint_report.infrastructure.auth.playwright_session import (
            load_saved_cookie,
        )
    except ImportError:
        return ""
    return load_saved_cookie()


def load_settings(env_path: Path | None = None) -> Settings:
    path = env_path or ENV_PATH
    load_dotenv(path, override=True)
    cookie = _cookie_from_disk() or os.getenv("ROVO_COOKIE", "").strip()
    return Settings(
        jira_base_url=os.getenv("JIRA_BASE_URL", "https://eduzzjira.atlassian.net").rstrip("/"),
        jira_cloud_id=os.getenv("JIRA_CLOUD_ID", ""),
        rovo_agent_id=os.getenv("ROVO_AGENT_ID", ""),
        rovo_cookie=cookie,
        rovo_conversation_id=os.getenv("ROVO_CONVERSATION_ID", "").strip(),
        tts_voice=os.getenv("TTS_VOICE", "pt-BR-AntonioNeural"),
    )


def with_board(settings: Settings, board: dict | None) -> Settings:
    """Attach selected board context (name + URL) for Rovo/Jira calls."""
    board = board or {}
    name = str(board.get("name") or "").strip()
    url = str(board.get("url") or "").strip() or settings.jira_base_url
    settings.board_name = name
    settings.board_url = url
    return settings
