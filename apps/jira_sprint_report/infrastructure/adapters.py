"""Concrete adapters implementing domain ports (open for extension)."""

from __future__ import annotations

from pathlib import Path

from jira_sprint_report.domain.models import (
    ChatResult,
    Settings,
    SlideSpec,
    SlideTheme,
    StructuredReport,
)
from jira_sprint_report.domain.ports import ProgressCallback
from jira_sprint_report.infrastructure.auth.playwright_session import (
    clear_saved_session,
    ensure_cookie,
    load_saved_cookie,
    login_and_capture,
)
from jira_sprint_report.infrastructure.jira.media import attach_media_to_slides
from jira_sprint_report.infrastructure.rovo.client import RovoClient
from jira_sprint_report.infrastructure.slides.renderer import build_pptx, export_pngs
from jira_sprint_report.infrastructure.tts.edge import synthesize_all
from jira_sprint_report.infrastructure.video.moviepy_builder import build_video


class PlaywrightSessionStore:
    def load_cookie(self) -> str:
        return load_saved_cookie()

    def clear(self) -> None:
        clear_saved_session()

    def ensure(self, base_url: str, board_url: str) -> str:
        return ensure_cookie(base_url, board_url, force_login=False)

    def login(self, base_url: str, board_url: str) -> str:
        return login_and_capture(base_url, board_url)


class RovoReportChat:
    def __init__(self, settings: Settings) -> None:
        self._client = RovoClient(settings)

    def chat(
        self,
        message: str,
        conversation_id: str | None = None,
    ) -> ChatResult:
        return self._client.chat(message, conversation_id=conversation_id)


class JiraMediaFetcher:
    def attach_to_slides(
        self,
        settings: Settings,
        slides: list[SlideSpec],
        media_dir: Path,
        *,
        max_per_issue: int = 3,
        on_progress: ProgressCallback | None = None,
    ) -> None:
        attach_media_to_slides(
            settings,
            slides,
            media_dir,
            max_per_issue=max_per_issue,
            on_progress=on_progress,
        )


class PillowPptxSlideRenderer:
    def export_pngs(
        self,
        report: StructuredReport,
        out_dir: Path,
        theme: SlideTheme | None = None,
    ) -> list[Path]:
        return export_pngs(report, out_dir, theme=theme)

    def build_pptx(
        self,
        report: StructuredReport,
        path: Path,
        *,
        png_paths: list[Path] | None = None,
        theme: SlideTheme | None = None,
    ) -> Path:
        return build_pptx(report, path, png_paths=png_paths, theme=theme)


class EdgeTtsEngine:
    def synthesize_all(
        self,
        slides: list[SlideSpec],
        out_dir: Path,
        voice: str,
        on_progress: ProgressCallback | None = None,
    ) -> list[Path]:
        return synthesize_all(slides, out_dir, voice, on_progress=on_progress)


class MoviePyVideoBuilder:
    def build(
        self,
        slide_pngs: list[Path],
        audio_files: list[Path],
        output_path: Path,
    ) -> Path:
        return build_video(slide_pngs, audio_files, output_path)
