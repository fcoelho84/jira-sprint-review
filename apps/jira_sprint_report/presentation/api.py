from __future__ import annotations

import threading
import traceback
from pathlib import Path
from typing import Any

import markdown as md
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from jira_sprint_report.application.services import build_container
from jira_sprint_report.domain.models import SlideTheme
from jira_sprint_report.infrastructure.config import OUTPUT_DIR, WEB_DIR
from jira_sprint_report.infrastructure.jira.boards import list_boards
from jira_sprint_report.presentation.schemas import (
    ApproveBody,
    BoardBody,
    PromptBody,
    ReviseBody,
    ThemeBody,
    VideoBody,
)

STATIC_DIR = WEB_DIR / "static"
TEMPLATES_DIR = WEB_DIR / "templates"

app = FastAPI(title="Sprint Report", docs_url=None, redoc_url=None)
STATIC_DIR.mkdir(parents=True, exist_ok=True)
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

_container = build_container()
_state = _container["state"]
_session = _container["session"]
_report = _container["report"]
_slides = _container["slides"]
_video = _container["video"]
_default_prompt = _container["default_prompt"]
_load_settings = _container["load_settings"]


def _md_html(text: str) -> str:
    return md.markdown(text or "", extensions=["fenced_code", "tables", "nl2br"])


def _board_dict(body: BoardBody | None) -> dict[str, Any] | None:
    if body is None:
        return None
    name = body.name.strip()
    url = body.url.strip()
    if not name or not url:
        return None
    return {
        "id": body.id,
        "name": name,
        "url": url,
        "project_key": (body.project_key or "").strip(),
        "type": (body.type or "").strip(),
    }


def _require_board(board: dict[str, Any] | None) -> dict[str, Any]:
    if not board or not board.get("name") or not board.get("url"):
        raise HTTPException(status_code=400, detail="Selecione um board (obrigatório)")
    return board


def _public_state() -> dict[str, Any]:
    settings = _load_settings()
    snap = _state.snapshot()
    png_urls = []
    for p in snap["png_paths"]:
        path = Path(p)
        try:
            rel = path.relative_to(OUTPUT_DIR)
            png_urls.append(f"/files/{rel.as_posix()}")
        except ValueError:
            png_urls.append("")
    video_url = None
    if snap["video_path"]:
        try:
            rel = Path(snap["video_path"]).relative_to(OUTPUT_DIR)
            video_url = f"/files/{rel.as_posix()}"
        except ValueError:
            video_url = None
    pptx_url = None
    if snap["pptx_path"]:
        try:
            rel = Path(snap["pptx_path"]).relative_to(OUTPUT_DIR)
            pptx_url = f"/files/{rel.as_posix()}"
        except ValueError:
            pptx_url = None
    return {
        "session_ok": settings.cookie_ok,
        "jira_base_url": settings.jira_base_url,
        "default_prompt": _default_prompt(),
        "conversation_id": snap["conversation_id"],
        "report_md": snap["report_md"],
        "report_html": _md_html(snap["report_md"]),
        "chat_history": snap["chat_history"],
        "slides": snap["slides"],
        "png_urls": png_urls,
        "pptx_url": pptx_url,
        "video_url": video_url,
        "job": dict(snap["job"]),
        "theme": dict(snap["theme"]),
        "renegotiations": snap.get("renegotiations", ""),
        "mid_sprint": snap.get("mid_sprint", ""),
        "board": snap.get("board"),
        "voices": [
            settings.tts_voice,
            "pt-BR-AntonioNeural",
            "pt-BR-FranciscaNeural",
            "pt-BR-BrendaNeural",
            "pt-BR-DonatoNeural",
        ],
    }


def _run_job(name: str, worker) -> None:
    try:
        worker()
    except Exception as exc:  # noqa: BLE001
        err = str(exc)
        if name == "video":
            err = f"{exc}\n{traceback.format_exc()}"
        _state.set_job(name, "error", error=err, progress=0)


def _login_target() -> str:
    settings = _load_settings()
    board = _state.get("board") or {}
    return str(board.get("url") or settings.jira_base_url)


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    html = (TEMPLATES_DIR / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(html)


@app.get("/api/state")
def api_state() -> dict[str, Any]:
    return _public_state()


@app.get("/api/boards")
def api_boards() -> dict[str, Any]:
    settings = _load_settings()
    try:
        cookie = _session.ensure(settings.jira_base_url, settings.jira_base_url)
        settings.rovo_cookie = cookie
        boards = list_boards(settings)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"boards": boards}


@app.post("/api/board")
def api_board(body: BoardBody) -> dict[str, Any]:
    board = _require_board(_board_dict(body))
    _state.set(board=board)
    return _public_state()


@app.post("/api/theme")
def api_theme(body: ThemeBody) -> dict[str, Any]:
    theme = SlideTheme.from_dict(body.model_dump()).as_public()
    _state.set(theme=theme)
    return _public_state()


@app.post("/api/login")
def api_login() -> dict[str, Any]:
    settings = _load_settings()
    try:
        _session.login(settings.jira_base_url, _login_target())
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return _public_state()


@app.post("/api/relogin")
def api_relogin() -> dict[str, Any]:
    settings = _load_settings()
    try:
        _session.clear()
        _session.login(settings.jira_base_url, _login_target())
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return _public_state()


@app.post("/api/report")
def api_report(body: PromptBody) -> dict[str, Any]:
    if _state.job_busy():
        raise HTTPException(status_code=409, detail="Já existe uma tarefa em andamento")
    board = _require_board(_board_dict(body.board) or _state.get("board"))
    prompt = (body.prompt or _default_prompt()).strip()
    _state.set(
        board=board,
        renegotiations=(body.renegotiations or "").strip(),
        mid_sprint=(body.mid_sprint or "").strip(),
    )
    _state.set_job("report", "running", "Iniciando...", progress=1, current=0, total=3)
    threading.Thread(
        target=_run_job,
        args=("report", lambda: _report.generate_report(prompt)),
        daemon=True,
    ).start()
    return _public_state()


@app.post("/api/revise")
def api_revise(body: ReviseBody) -> dict[str, Any]:
    if _state.job_busy():
        raise HTTPException(status_code=409, detail="Já existe uma tarefa em andamento")
    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Mensagem vazia")
    updates: dict[str, Any] = {}
    board = _board_dict(body.board)
    if board is not None:
        updates["board"] = _require_board(board)
    elif not (_state.get("board") or {}).get("name"):
        raise HTTPException(status_code=400, detail="Selecione um board (obrigatório)")
    if body.renegotiations is not None:
        updates["renegotiations"] = body.renegotiations.strip()
    if body.mid_sprint is not None:
        updates["mid_sprint"] = body.mid_sprint.strip()
    if updates:
        _state.set(**updates)
    conv = _state.get("conversation_id")
    _state.set_job("revise", "running", "Iniciando...", progress=1, current=0, total=2)
    threading.Thread(
        target=_run_job,
        args=("revise", lambda: _report.revise_report(message, body.report_md, conv)),
        daemon=True,
    ).start()
    return _public_state()


@app.post("/api/save-report")
def api_save_report(body: ApproveBody) -> dict[str, Any]:
    _state.set(report_md=body.report_md)
    run = _state.run_dir()
    (run / "report.md").write_text(body.report_md, encoding="utf-8")
    return _public_state()


@app.post("/api/approve")
def api_approve(body: ApproveBody) -> dict[str, Any]:
    _report.approve(body.report_md)
    return _public_state()


@app.post("/api/slides")
def api_slides() -> dict[str, Any]:
    if _state.job_busy():
        raise HTTPException(status_code=409, detail="Já existe uma tarefa em andamento")
    if not _state.structured() and not _state.get("report_md"):
        raise HTTPException(status_code=400, detail="Aprove um relatório antes")
    _state.set_job("slides", "running", "Iniciando...", progress=1, current=0, total=3)
    threading.Thread(target=_run_job, args=("slides", _slides.generate), daemon=True).start()
    return _public_state()


@app.post("/api/video")
def api_video(body: VideoBody) -> dict[str, Any]:
    if _state.job_busy():
        raise HTTPException(status_code=409, detail="Já existe uma geração em andamento")
    if not _state.get("png_paths"):
        raise HTTPException(status_code=400, detail="Gere os slides antes")
    _state.set_job("video", "running", "Iniciando...", progress=1, current=0, total=1)
    threading.Thread(
        target=_run_job,
        args=("video", lambda: _video.generate(body.voice)),
        daemon=True,
    ).start()
    return _public_state()


@app.get("/files/{file_path:path}")
def get_file(file_path: str) -> FileResponse:
    target = (OUTPUT_DIR / file_path).resolve()
    if not str(target).startswith(str(OUTPUT_DIR.resolve())):
        raise HTTPException(status_code=403, detail="Forbidden")
    if not target.exists():
        raise HTTPException(status_code=404, detail="Arquivo não encontrado")
    return FileResponse(target)
