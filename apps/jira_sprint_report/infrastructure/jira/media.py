from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx

from jira_sprint_report.domain.models import Settings

IMAGE_MIME_PREFIXES = ("image/",)
VIDEO_MIME_PREFIXES = ("video/",)
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
VIDEO_EXTS = {".mp4", ".webm", ".mov", ".mkv", ".avi"}
_ISSUE_KEY_RE = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")


def issue_keys_from_text(text: str) -> list[str]:
    seen: set[str] = set()
    keys: list[str] = []
    for match in _ISSUE_KEY_RE.finditer(text or ""):
        key = match.group(1)
        if key not in seen:
            seen.add(key)
            keys.append(key)
    return keys


def _headers(settings: Settings) -> dict[str, str]:
    if not settings.rovo_cookie:
        raise RuntimeError("Sessão Jira ausente para baixar mídias.")
    return {
        "accept": "*/*",
        "user-agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36"
        ),
        "cookie": settings.rovo_cookie,
        "referer": settings.board_url or settings.jira_base_url,
    }


def _is_image(mime: str, filename: str) -> bool:
    mime = (mime or "").lower()
    ext = Path(filename or "").suffix.lower()
    return mime.startswith(IMAGE_MIME_PREFIXES) or ext in IMAGE_EXTS


def _is_video(mime: str, filename: str) -> bool:
    mime = (mime or "").lower()
    ext = Path(filename or "").suffix.lower()
    return mime.startswith(VIDEO_MIME_PREFIXES) or ext in VIDEO_EXTS


def _walk_media_ids(node: Any, found: list[str]) -> None:
    if isinstance(node, dict):
        if node.get("type") == "media":
            attrs = node.get("attrs") or {}
            media_id = attrs.get("id")
            if media_id:
                found.append(str(media_id))
        for value in node.values():
            _walk_media_ids(value, found)
    elif isinstance(node, list):
        for item in node:
            _walk_media_ids(item, found)


def _extract_frame(video_path: Path, out_path: Path) -> Path | None:
    try:
        import imageio_ffmpeg

        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        ffmpeg = "ffmpeg"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-q:v",
        "2",
        str(out_path),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=60)
    except Exception:
        return None
    return out_path if out_path.exists() and out_path.stat().st_size > 0 else None


def _download(
    client: httpx.Client,
    url: str,
    dest: Path,
) -> Path | None:
    try:
        with client.stream("GET", url, follow_redirects=True) as response:
            if response.status_code >= 400:
                return None
            dest.parent.mkdir(parents=True, exist_ok=True)
            with dest.open("wb") as fh:
                for chunk in response.iter_bytes():
                    fh.write(chunk)
        if dest.stat().st_size == 0:
            dest.unlink(missing_ok=True)
            return None
        return dest
    except Exception:
        return None


def fetch_issue_illustrations(
    settings: Settings,
    issue_key: str,
    out_dir: Path,
    max_images: int = 3,
) -> list[Path]:
    """Download images (and first frame of videos) from issue attachments/comments."""
    out_dir.mkdir(parents=True, exist_ok=True)
    url = (
        f"{settings.jira_base_url}/rest/api/3/issue/{issue_key}"
        f"?fields=attachment,comment"
    )
    images: list[Path] = []

    with httpx.Client(headers=_headers(settings), timeout=60.0) as client:
        response = client.get(url)
        if response.status_code in (401, 403):
            raise RuntimeError(f"Sem permissão para ler {issue_key} (HTTP {response.status_code})")
        if response.status_code >= 400:
            return []
        data = response.json()
        fields = data.get("fields") or {}

        # 1) Classic attachments
        for idx, att in enumerate(fields.get("attachment") or []):
            if len(images) >= max_images:
                break
            filename = att.get("filename") or f"att-{idx}"
            mime = att.get("mimeType") or ""
            content = att.get("content") or ""
            thumb = att.get("thumbnail") or ""
            if not content and not thumb:
                continue

            safe = re.sub(r"[^A-Za-z0-9._-]+", "_", filename)
            if _is_image(mime, filename):
                dest = out_dir / f"{issue_key}-att-{idx}-{safe}"
                path = _download(client, content or thumb, dest)
                if path:
                    images.append(path)
            elif _is_video(mime, filename):
                video_dest = out_dir / f"{issue_key}-vid-{idx}-{safe}"
                video_path = _download(client, content, video_dest)
                if video_path:
                    frame = _extract_frame(video_path, out_dir / f"{issue_key}-vid-{idx}.jpg")
                    if frame:
                        images.append(frame)

        # 2) Media embedded in comments (ADF)
        comments = ((fields.get("comment") or {}).get("comments")) or []
        media_ids: list[str] = []
        for comment in comments:
            body = comment.get("body")
            _walk_media_ids(body, media_ids)

        for idx, media_id in enumerate(dict.fromkeys(media_ids)):
            if len(images) >= max_images:
                break
            # Prefer attachment content endpoint; fallbacks for media API variants
            candidates = [
                f"{settings.jira_base_url}/rest/api/3/attachment/content/{media_id}",
                f"{settings.jira_base_url}/rest/api/3/attachment/{media_id}",
                urljoin(
                    settings.jira_base_url + "/",
                    f"rest/api/3/issue/{issue_key}/attachments/{media_id}",
                ),
            ]
            dest = out_dir / f"{issue_key}-media-{idx}"
            saved: Path | None = None
            for candidate in candidates:
                saved = _download(client, candidate, dest)
                if saved:
                    break
            if not saved:
                continue

            # Detect type by content / name
            mime = ""
            try:
                from PIL import Image as PILImage

                PILImage.open(saved).verify()
                images.append(saved)
                continue
            except Exception:
                pass

            frame = _extract_frame(saved, out_dir / f"{issue_key}-media-{idx}.jpg")
            if frame:
                images.append(frame)
            else:
                # Unknown binary — drop
                saved.unlink(missing_ok=True)

    return images[:max_images]


def attach_media_to_slides(
    settings: Settings,
    slides: list[Any],
    media_dir: Path,
    max_per_issue: int = 3,
    on_progress=None,
) -> None:
    """Mutates slides in place: fills image_paths for content slides with issue_key."""
    cache: dict[str, list[Path]] = {}
    keys = []
    for slide in slides:
        key = getattr(slide, "issue_key", None)
        if key and getattr(slide, "kind", "") == "content" and key not in keys:
            keys.append(key)
    total = max(len(keys), 1)
    for i, key in enumerate(keys, start=1):
        if on_progress:
            on_progress(i - 1, total, f"Mídia {key} ({i}/{total})")
        try:
            cache[key] = fetch_issue_illustrations(
                settings, key, media_dir / key, max_images=max_per_issue
            )
        except Exception:
            cache[key] = []
        if on_progress:
            on_progress(i, total, f"Mídia {key} ({i}/{total})")
    for slide in slides:
        key = getattr(slide, "issue_key", None)
        if not key or getattr(slide, "kind", "") != "content":
            continue
        slide.image_paths = [str(p) for p in cache.get(key, [])]
