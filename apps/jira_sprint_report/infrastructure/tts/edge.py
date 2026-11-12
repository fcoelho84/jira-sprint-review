from __future__ import annotations

import asyncio
from pathlib import Path

import edge_tts

from jira_sprint_report.domain.models import SlideSpec


async def _synthesize(text: str, path: Path, voice: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    communicate = edge_tts.Communicate(text or " ", voice=voice)
    await communicate.save(str(path))
    return path


def synthesize_slide(text: str, path: Path, voice: str) -> Path:
    return asyncio.run(_synthesize(text, path, voice))


def synthesize_all(
    slides: list[SlideSpec],
    out_dir: Path,
    voice: str,
    on_progress=None,
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    total = max(len(slides), 1)

    async def run_all() -> list[Path]:
        paths: list[Path] = []
        for i, slide in enumerate(slides, start=1):
            path = out_dir / f"slide-{i:02d}.mp3"
            await _synthesize(slide.narration or slide.title, path, voice)
            paths.append(path)
            if on_progress:
                on_progress(i, total, f"Áudio {i}/{total}")
        return paths

    return asyncio.run(run_all())
