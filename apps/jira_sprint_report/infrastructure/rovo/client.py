from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import httpx

from jira_sprint_report.domain.models import ChatResult, Settings


class RovoAuthError(Exception):
    """Cookie/session expired or unauthorized."""


class RovoError(Exception):
    """Generic Rovo client error."""


ProgressCb = Callable[[str], None]


def _adf_paragraph(text: str) -> dict[str, Any]:
    return {
        "content": {
            "version": 1,
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": text}],
                }
            ],
        },
        "context": {
            "browser_url": "",
            "useCurrentBrowsingContext": False,
            "webSearchEnabled": False,
            "deepResearchEnabled": False,
            "creationContext": {
                "isStagingArea": False,
                "productKey": "jira",
                "isViewMode": False,
                "isDraftLockedForEditing": False,
            },
            "userTimezone": "America/Sao_Paulo",
            "fileIds": [],
            "knowledgeEnabled": True,
            "filters": {
                "knowledgeSources": [
                    "jira",
                    "atlas_goal",
                    "atlas_project",
                    "help_aggregator",
                ]
            },
            "shouldExtractConversationScopes": False,
        },
        "agent_id": "",
        "mimeType": "text/adf",
        "store_message": False,
        "citations_enabled": True,
        "browser_display_context_active": False,
    }


def _walk_adf_text(node: Any, parts: list[str]) -> None:
    if isinstance(node, dict):
        if node.get("type") == "text" and isinstance(node.get("text"), str):
            parts.append(node["text"])
        for value in node.values():
            _walk_adf_text(value, parts)
    elif isinstance(node, list):
        for item in node:
            _walk_adf_text(item, parts)


def extract_text_from_payload(payload: Any) -> str:
    """Best-effort extraction of assistant text from Rovo SSE JSON payloads."""
    if payload is None:
        return ""
    if isinstance(payload, str):
        return payload

    candidates: list[str] = []

    def consider(value: Any) -> None:
        if isinstance(value, str) and value.strip():
            candidates.append(value)

    if isinstance(payload, dict):
        for key in (
            "text",
            "message",
            "content",
            "delta",
            "answer",
            "markdown",
            "plainText",
            "response",
        ):
            if key in payload:
                val = payload[key]
                if isinstance(val, str):
                    consider(val)
                elif isinstance(val, dict):
                    adf_parts: list[str] = []
                    _walk_adf_text(val, adf_parts)
                    if adf_parts:
                        candidates.append("".join(adf_parts))
                    consider(val.get("text"))

        # Nested message / data shapes commonly seen in AI streams
        for nest_key in ("data", "message", "payload", "result", "event"):
            nested = payload.get(nest_key)
            if nested is not None and nested is not payload:
                extracted = extract_text_from_payload(nested)
                if extracted:
                    candidates.append(extracted)

        adf_parts: list[str] = []
        _walk_adf_text(payload, adf_parts)
        if adf_parts:
            candidates.append("".join(adf_parts))

    # Prefer the longest non-trivial candidate (final answer tends to be longest)
    cleaned = [c.strip() for c in candidates if c and c.strip()]
    if not cleaned:
        return ""
    return max(cleaned, key=len)


def parse_sse_lines(lines: Iterator[str]) -> Iterator[dict[str, Any]]:
    data_buf: list[str] = []
    event_name = "message"

    def flush() -> dict[str, Any] | None:
        nonlocal data_buf, event_name
        if not data_buf:
            return None
        raw = "\n".join(data_buf)
        data_buf = []
        name = event_name
        event_name = "message"
        if raw in ("[DONE]", "done", ""):
            return {"event": "done", "data": raw}
        try:
            parsed = json.loads(raw)
            return {"event": name, "data": parsed}
        except json.JSONDecodeError:
            return {"event": name, "data": raw}

    for line in lines:
        line = line.rstrip("\r")
        if not line:
            item = flush()
            if item is not None:
                yield item
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event_name = line[6:].strip() or "message"
            continue
        if line.startswith("data:"):
            data_buf.append(line[5:].lstrip())
            continue
        # Some servers send bare JSON lines
        if line.startswith("{"):
            data_buf.append(line)

    item = flush()
    if item is not None:
        yield item


class RovoClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    def _headers(self) -> dict[str, str]:
        if not self.settings.rovo_cookie:
            raise RovoAuthError("ROVO_COOKIE vazio. Cole o cookie no .env ou use Renovar login.")
        if not self.settings.jira_cloud_id:
            raise RovoError("JIRA_CLOUD_ID não configurado.")
        return {
            "accept": "*/*",
            "accept-language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
            "content-type": "application/json;charset=UTF-8",
            "origin": self.settings.jira_base_url,
            "referer": self.settings.board_url or self.settings.jira_base_url,
            "user-agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36"
            ),
            "x-answer-now-ui-opt-in": "true",
            "x-channel-id": "rovo-chat",
            "x-cloudid": self.settings.jira_cloud_id,
            "x-experience-id": "ai-mate",
            "x-product": "jira",
            "x-rovo-chat-capabilities": (
                '["ask-question-enabled","interaction-conclusion-v1",'
                '"inline_lumina_enabled","tool_resumption_enabled",'
                '"actionable-follow-ups-stacked","store-message-from-user-settings"]'
            ),
            "cookie": self.settings.rovo_cookie,
        }

    def stream_url(self, conversation_id: str) -> str:
        return (
            f"{self.settings.jira_base_url}/gateway/api/assist/rovo/v1/chat/"
            f"conversation/{conversation_id}/message/stream/sse"
        )

    def build_body(self, text: str) -> dict[str, Any]:
        body = _adf_paragraph(text)
        body["agent_id"] = self.settings.rovo_agent_id
        body["context"]["browser_url"] = self.settings.board_url or self.settings.jira_base_url
        return body

    def chat(
        self,
        message: str,
        conversation_id: str | None = None,
        on_delta: ProgressCb | None = None,
        timeout: float = 300.0,
    ) -> ChatResult:
        conv_id = conversation_id or self.settings.rovo_conversation_id or str(uuid.uuid4())
        url = self.stream_url(conv_id)
        body = self.build_body(message)
        headers = self._headers()

        text_parts: list[str] = []
        latest_full = ""
        raw_events: list[dict[str, Any]] = []

        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            with client.stream("POST", url, headers=headers, json=body) as response:
                if response.status_code in (401, 403):
                    raise RovoAuthError(
                        f"Sessão inválida/expirada (HTTP {response.status_code}). "
                        "Atualize ROVO_COOKIE ou use Renovar login."
                    )
                if response.status_code >= 400:
                    err_body = response.read().decode("utf-8", errors="replace")[:800]
                    raise RovoError(f"Rovo HTTP {response.status_code}: {err_body}")

                def line_iter() -> Iterator[str]:
                    for line in response.iter_lines():
                        yield line

                for event in parse_sse_lines(line_iter()):
                    raw_events.append(event)
                    data = event.get("data")
                    chunk = extract_text_from_payload(data)

                    # Track incremental deltas vs full replacements
                    if chunk:
                        if latest_full and chunk.startswith(latest_full):
                            delta = chunk[len(latest_full) :]
                            latest_full = chunk
                            if delta and on_delta:
                                on_delta(delta)
                        elif len(chunk) > len(latest_full) + 20 or not latest_full:
                            # Likely a fuller snapshot
                            if on_delta and chunk != latest_full:
                                # Stream only new suffix if possible
                                if latest_full and chunk.startswith(latest_full[: max(1, len(latest_full) // 2)]):
                                    on_delta(chunk[len(latest_full) :] if chunk.startswith(latest_full) else chunk)
                                else:
                                    on_delta(chunk if not latest_full else "")
                            latest_full = chunk if len(chunk) >= len(latest_full) else latest_full
                            if len(chunk) >= len(latest_full):
                                latest_full = chunk
                        else:
                            text_parts.append(chunk)
                            if on_delta:
                                on_delta(chunk)

        final = latest_full.strip()
        if not final and text_parts:
            final = "".join(text_parts).strip()
        if not final:
            # Last resort: dump any string fields from last events
            for event in reversed(raw_events):
                piece = extract_text_from_payload(event.get("data"))
                if piece:
                    final = piece
                    break

        if not final:
            raise RovoError(
                "Stream terminou sem texto utilizável. "
                "Verifique o cookie/agent_id ou inspecione raw_events."
            )

        return ChatResult(conversation_id=conv_id, text=final, raw_events=raw_events)
