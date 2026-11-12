from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from .models import ChatResult, Settings, SlideSpec, SlideTheme, StructuredReport

ProgressCallback = Callable[[int, int, str], None]


class SessionStore(Protocol):
    def load_cookie(self) -> str: ...

    def clear(self) -> None: ...

    def ensure(self, base_url: str, board_url: str) -> str: ...

    def login(self, base_url: str, board_url: str) -> str: ...


class ReportChat(Protocol):
    def chat(
        self,
        message: str,
        conversation_id: str | None = None,
    ) -> ChatResult: ...


class MediaFetcher(Protocol):
    def attach_to_slides(
        self,
        settings: Settings,
        slides: list[SlideSpec],
        media_dir: Path,
        *,
        max_per_issue: int = 3,
        on_progress: ProgressCallback | None = None,
    ) -> None: ...


class SlideRenderer(Protocol):
    def export_pngs(
        self,
        report: StructuredReport,
        out_dir: Path,
        theme: SlideTheme | None = None,
    ) -> list[Path]: ...

    def build_pptx(
        self,
        report: StructuredReport,
        path: Path,
        *,
        png_paths: list[Path] | None = None,
        theme: SlideTheme | None = None,
    ) -> Path: ...


class TtsEngine(Protocol):
    def synthesize_all(
        self,
        slides: list[SlideSpec],
        out_dir: Path,
        voice: str,
        on_progress: ProgressCallback | None = None,
    ) -> list[Path]: ...


class VideoBuilder(Protocol):
    def build(
        self,
        slide_pngs: list[Path],
        audio_files: list[Path],
        output_path: Path,
    ) -> Path: ...
