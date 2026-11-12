from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from jira_sprint_report.domain.models import SlideTheme, StructuredReport
from jira_sprint_report.infrastructure.config import OUTPUT_DIR


class AppState:
    """In-memory session state for the local single-user app."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data: dict[str, Any] = {
            "conversation_id": None,
            "report_md": "",
            "chat_history": [],
            "slides": [],
            "run_dir": None,
            "pptx_path": None,
            "png_paths": [],
            "audio_paths": [],
            "video_path": None,
            "theme": SlideTheme().as_public(),
            "renegotiations": "",
            "mid_sprint": "",
            "board": None,
            "_structured": None,
            "job": {
                "name": None,
                "status": "idle",
                "message": "",
                "error": "",
                "progress": 0,
                "current": 0,
                "total": 0,
            },
        }

    def set_job(
        self,
        name: str | None,
        status: str,
        message: str = "",
        error: str = "",
        progress: int | None = None,
        current: int | None = None,
        total: int | None = None,
    ) -> None:
        with self._lock:
            job = dict(self._data["job"])
            job["name"] = name
            job["status"] = status
            job["message"] = message
            job["error"] = error
            if progress is not None:
                job["progress"] = max(0, min(100, int(progress)))
            if current is not None:
                job["current"] = int(current)
            if total is not None:
                job["total"] = int(total)
            self._data["job"] = job

    def job_busy(self) -> bool:
        with self._lock:
            return self._data["job"].get("status") == "running"

    def run_dir(self) -> Path:
        with self._lock:
            if not self._data["run_dir"]:
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                path = OUTPUT_DIR / stamp
                path.mkdir(parents=True, exist_ok=True)
                self._data["run_dir"] = str(path)
            return Path(self._data["run_dir"])

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._data.get(key, default)

    def set(self, **kwargs: Any) -> None:
        with self._lock:
            self._data.update(kwargs)

    def update(self, mutator) -> None:
        with self._lock:
            mutator(self._data)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._data)

    def structured(self) -> StructuredReport | None:
        with self._lock:
            return self._data.get("_structured")
