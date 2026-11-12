"""Entrypoint — keeps `uvicorn server:app` working."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "apps"))

from jira_sprint_report.presentation.api import app  # noqa: E402

__all__ = ["app"]

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server:app", host="0.0.0.0", port=8501, reload=False)
