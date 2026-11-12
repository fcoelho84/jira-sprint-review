"""Use cases depend on ports — swap adapters without changing orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jira_sprint_report.application.prompt_builder import build_prompt, default_prompt
from jira_sprint_report.application.report_structurer import structure_report
from jira_sprint_report.application.state import AppState
from jira_sprint_report.domain.models import Settings, SlideTheme, StructuredReport
from jira_sprint_report.domain.ports import (
    MediaFetcher,
    ReportChat,
    SessionStore,
    SlideRenderer,
    TtsEngine,
    VideoBuilder,
)
from jira_sprint_report.infrastructure.adapters import (
    EdgeTtsEngine,
    JiraMediaFetcher,
    MoviePyVideoBuilder,
    PillowPptxSlideRenderer,
    PlaywrightSessionStore,
    RovoReportChat,
)
from jira_sprint_report.infrastructure.config import load_settings, with_board


def slides_payload(structured: StructuredReport) -> list[dict[str, Any]]:
    return [
        {
            "title": s.title,
            "bullets": s.bullets,
            "narration": s.narration,
            "kind": s.kind,
            "issue_key": s.issue_key,
            "images": len(s.image_paths),
        }
        for s in structured.slides
    ]


class ReportService:
    def __init__(
        self,
        state: AppState,
        session: SessionStore,
        chat_factory=None,
    ) -> None:
        self.state = state
        self.session = session
        self._chat_factory = chat_factory or (lambda settings: RovoReportChat(settings))

    def _settings(self) -> Settings:
        settings = with_board(load_settings(), self.state.get("board"))
        cookie = self.session.ensure(
            settings.jira_base_url,
            settings.board_url or settings.jira_base_url,
        )
        settings.rovo_cookie = cookie
        return settings

    def generate_report(self, prompt: str) -> None:
        board = self.state.get("board") or {}
        if not (board.get("name") and board.get("url")):
            raise RuntimeError("Selecione um board antes de gerar o relatório.")
        self.state.set_job("report", "running", "Garantindo sessão...", progress=5, current=0, total=3)
        settings = self._settings()
        self.state.set_job("report", "running", "Consultando Rovo...", progress=20, current=1, total=3)
        chat: ReportChat = self._chat_factory(settings)
        full_prompt = build_prompt(
            prompt,
            renegotiations=self.state.get("renegotiations", ""),
            mid_sprint=self.state.get("mid_sprint", ""),
            board_name=str(board.get("name") or ""),
        )
        result = chat.chat(full_prompt, conversation_id=None)
        self.state.set_job("report", "running", "Salvando relatório...", progress=90, current=2, total=3)
        run = self.state.run_dir()
        (run / "report.md").write_text(result.text, encoding="utf-8")
        self.state.set(
            conversation_id=result.conversation_id,
            report_md=result.text,
            chat_history=[
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": result.text},
            ],
            slides=[],
            png_paths=[],
            pptx_path=None,
            audio_paths=[],
            video_path=None,
            _structured=None,
        )
        self.state.set_job("report", "done", "Relatório gerado.", progress=100, current=3, total=3)

    def revise_report(self, message: str, report_md: str | None, conv: str | None) -> None:
        board = self.state.get("board") or {}
        if not (board.get("name") and board.get("url")):
            raise RuntimeError("Selecione um board antes de revisar o relatório.")
        self.state.set_job("revise", "running", "Enviando ao Rovo...", progress=15, current=0, total=2)
        settings = self._settings()
        if report_md is not None:
            self.state.set(report_md=report_md)
        chat: ReportChat = self._chat_factory(settings)
        mid = self.state.get("mid_sprint", "")
        reno = self.state.get("renegotiations", "")
        board_name = str(board.get("name") or "")
        final_msg = message
        reminders: list[str] = []
        if board_name:
            reminders.append(f"Board selecionado: {board_name}.")
        if mid or reno:
            reminders.append(
                "Mantenha separadas as seções "
                "Entregas do planejamento / Entraram após o início / Renegociações "
                "conforme as notas do usuário, se ainda fizer sentido."
            )
        if reminders:
            final_msg = f"{message}\n\n(Lembrete: {' '.join(reminders)})"
            if mid:
                final_msg += f"\n\nEntraram após o início (notas do usuário):\n{mid}"
            if reno:
                final_msg += f"\n\nRenegociações (notas do usuário):\n{reno}"
        result = chat.chat(final_msg, conversation_id=conv)
        self.state.set_job("revise", "running", "Salvando...", progress=85, current=1, total=2)
        run = self.state.run_dir()
        (run / "report.md").write_text(result.text, encoding="utf-8")

        def append_history(data: dict) -> None:
            data["conversation_id"] = result.conversation_id
            data["report_md"] = result.text
            data["chat_history"].append({"role": "user", "content": message})
            data["chat_history"].append({"role": "assistant", "content": result.text})

        self.state.update(append_history)
        self.state.set_job("revise", "done", "Relatório atualizado.", progress=100, current=2, total=2)

    def approve(self, report_md: str) -> StructuredReport:
        board = self.state.get("board") or {}
        label = str(board.get("name") or "").strip() or "Sprint atual"
        structured = structure_report(report_md, sprint_label=label)
        self.state.set(
            report_md=report_md,
            slides=slides_payload(structured),
            _structured=structured,
            png_paths=[],
            pptx_path=None,
            video_path=None,
        )
        return structured


class SlidesService:
    def __init__(
        self,
        state: AppState,
        session: SessionStore,
        media: MediaFetcher | None = None,
        renderer: SlideRenderer | None = None,
    ) -> None:
        self.state = state
        self.session = session
        self.media = media or JiraMediaFetcher()
        self.renderer = renderer or PillowPptxSlideRenderer()

    def generate(self) -> None:
        structured = self.state.structured()
        report_md = self.state.get("report_md")
        if structured is None:
            if not report_md:
                raise RuntimeError("Aprove um relatório antes")
            structured = structure_report(report_md)
            self.state.set(_structured=structured, slides=slides_payload(structured))

        run = self.state.run_dir()
        settings = with_board(load_settings(), self.state.get("board"))
        self.state.set_job("slides", "running", "Baixando mídias do Jira...", progress=5, current=0, total=3)

        def media_progress(cur: int, total: int, msg: str) -> None:
            pct = 5 + int((cur / max(total, 1)) * 50)
            self.state.set_job("slides", "running", msg, progress=pct, current=cur, total=total)

        try:
            settings.rovo_cookie = self.session.ensure(
                settings.jira_base_url,
                settings.board_url or settings.jira_base_url,
            )
            self.media.attach_to_slides(
                settings,
                structured.slides,
                run / "media",
                max_per_issue=3,
                on_progress=media_progress,
            )
        except Exception as exc:  # noqa: BLE001
            self.state.set_job(
                "slides",
                "running",
                f"Seguindo sem mídia ({exc})",
                progress=55,
                current=0,
                total=3,
            )

        theme = SlideTheme.from_dict(self.state.get("theme"))
        self.state.set_job("slides", "running", "Renderizando PNGs...", progress=60, current=1, total=3)
        pngs = self.renderer.export_pngs(structured, run / "slides", theme=theme)
        self.state.set_job("slides", "running", "Montando PPTX...", progress=85, current=2, total=3)
        pptx = self.renderer.build_pptx(
            structured, run / "sprint-report.pptx", png_paths=pngs, theme=theme
        )
        self.state.set(
            _structured=structured,
            slides=slides_payload(structured),
            png_paths=[str(p) for p in pngs],
            pptx_path=str(pptx),
        )
        self.state.set_job(
            "slides",
            "done",
            f"{len(pngs)} slides prontos.",
            progress=100,
            current=3,
            total=3,
        )


class VideoService:
    def __init__(
        self,
        state: AppState,
        tts: TtsEngine | None = None,
        video: VideoBuilder | None = None,
    ) -> None:
        self.state = state
        self.tts = tts or EdgeTtsEngine()
        self.video = video or MoviePyVideoBuilder()

    def generate(self, voice: str) -> None:
        structured = self.state.structured()
        png_paths = list(self.state.get("png_paths") or [])
        if structured is None or not png_paths:
            raise RuntimeError("Gere os slides antes do vídeo")

        n = len(structured.slides)
        self.state.set_job(
            "video",
            "running",
            f"Gerando áudio (0/{n})...",
            progress=2,
            current=0,
            total=n + 1,
        )
        run = self.state.run_dir()

        def audio_progress(cur: int, total: int, msg: str) -> None:
            pct = 2 + int((cur / max(total, 1)) * 73)
            self.state.set_job("video", "running", msg, progress=pct, current=cur, total=total + 1)

        audios = self.tts.synthesize_all(
            structured.slides, run / "audio", voice, on_progress=audio_progress
        )
        self.state.set_job(
            "video",
            "running",
            "Montando MP4 (pode demorar)...",
            progress=78,
            current=n,
            total=n + 1,
        )
        out = self.video.build(
            [Path(p) for p in png_paths], audios, run / "sprint-report.mp4"
        )
        self.state.set(
            audio_paths=[str(a) for a in audios],
            video_path=str(out),
        )
        self.state.set_job(
            "video",
            "done",
            f"Vídeo pronto: {out.name}",
            progress=100,
            current=n + 1,
            total=n + 1,
        )


def build_container(state: AppState | None = None) -> dict[str, Any]:
    """Composition root — wiring lives here, not in handlers."""
    app_state = state or AppState()
    session = PlaywrightSessionStore()
    return {
        "state": app_state,
        "session": session,
        "report": ReportService(app_state, session),
        "slides": SlidesService(app_state, session),
        "video": VideoService(app_state),
        "default_prompt": default_prompt,
        "load_settings": load_settings,
    }
