from __future__ import annotations

from pydantic import BaseModel, Field


class BoardBody(BaseModel):
    id: int | str
    name: str
    url: str
    project_key: str = ""
    type: str = ""


class PromptBody(BaseModel):
    prompt: str = Field(default="")
    renegotiations: str = Field(default="")
    mid_sprint: str = Field(default="")
    board: BoardBody | None = None


class ReviseBody(BaseModel):
    message: str
    report_md: str | None = None
    renegotiations: str | None = None
    mid_sprint: str | None = None
    board: BoardBody | None = None


class ApproveBody(BaseModel):
    report_md: str


class VideoBody(BaseModel):
    voice: str = "pt-BR-AntonioNeural"


class ThemeBody(BaseModel):
    background: str = "#121c30"
    title: str = "#f0f4fa"
    body: str = "#a0b0c6"
    accent: str = "#22a898"
