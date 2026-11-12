from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Settings:
    jira_base_url: str
    jira_cloud_id: str
    rovo_agent_id: str
    rovo_cookie: str
    rovo_conversation_id: str
    tts_voice: str
    board_url: str = ""
    board_name: str = ""

    @property
    def cookie_ok(self) -> bool:
        cookie = self.rovo_cookie.strip()
        return bool(cookie) and (
            "tenant.session.token=" in cookie or "cloud.session.token=" in cookie
        )


@dataclass
class SlideSpec:
    title: str
    bullets: list[str] = field(default_factory=list)
    narration: str = ""
    kind: str = "content"  # cover | summary | content | closing
    issue_key: str | None = None
    image_paths: list[str] = field(default_factory=list)


@dataclass
class StructuredReport:
    title: str
    markdown: str
    slides: list[SlideSpec]


@dataclass
class ChatResult:
    conversation_id: str
    text: str
    raw_events: list[dict[str, Any]] = field(default_factory=list)


def _hex_to_rgb(value: str, fallback: tuple[int, int, int]) -> tuple[int, int, int]:
    raw = (value or "").strip().lstrip("#")
    if len(raw) == 3:
        raw = "".join(ch * 2 for ch in raw)
    if len(raw) != 6:
        return fallback
    try:
        return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)
    except ValueError:
        return fallback


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(int(round(x + (y - x) * t)) for x, y in zip(a, b))  # type: ignore[return-value]


@dataclass
class SlideTheme:
    background: str = "#121c30"
    title: str = "#f0f4fa"
    body: str = "#a0b0c6"
    accent: str = "#22a898"

    def as_public(self) -> dict[str, str]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> "SlideTheme":
        data = data or {}
        base = cls()
        return cls(
            background=str(data.get("background") or base.background),
            title=str(data.get("title") or base.title),
            body=str(data.get("body") or base.body),
            accent=str(data.get("accent") or base.accent),
        )

    def resolved(self) -> dict[str, tuple[int, int, int]]:
        bg = _hex_to_rgb(self.background, (18, 28, 48))
        title = _hex_to_rgb(self.title, (240, 244, 250))
        body = _hex_to_rgb(self.body, (160, 176, 198))
        accent = _hex_to_rgb(self.accent, (34, 168, 152))
        card = _mix(bg, title, 0.12)
        return {
            "bg": bg,
            "title": title,
            "body": body,
            "accent": accent,
            "card": card,
            "muted": body,
        }
