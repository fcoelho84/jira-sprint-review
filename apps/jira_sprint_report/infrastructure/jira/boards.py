from __future__ import annotations

from typing import Any

import httpx

from jira_sprint_report.domain.models import Settings


def board_url(settings: Settings, board_id: int | str, project_key: str) -> str:
    base = settings.jira_base_url.rstrip("/")
    key = (project_key or "").strip()
    if key:
        return f"{base}/jira/software/projects/{key}/boards/{board_id}"
    return f"{base}/jira/software/boards/{board_id}"


def list_boards(settings: Settings, *, max_results: int = 100) -> list[dict[str, Any]]:
    """List Jira Software boards visible to the current session."""
    if not settings.rovo_cookie:
        raise RuntimeError("Faça login no Jira antes de listar boards.")

    headers = {
        "accept": "application/json",
        "cookie": settings.rovo_cookie,
        "user-agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36"
        ),
        "referer": settings.jira_base_url,
    }

    boards: list[dict[str, Any]] = []
    start = 0
    with httpx.Client(headers=headers, timeout=60.0, follow_redirects=True) as client:
        while True:
            response = client.get(
                f"{settings.jira_base_url}/rest/agile/1.0/board",
                params={"startAt": start, "maxResults": max_results},
            )
            if response.status_code in (401, 403):
                raise RuntimeError(
                    f"Sessão inválida ao listar boards (HTTP {response.status_code})."
                )
            if response.status_code >= 400:
                raise RuntimeError(
                    f"Falha ao listar boards (HTTP {response.status_code}): "
                    f"{response.text[:300]}"
                )
            data = response.json()
            values = data.get("values") or []
            for item in values:
                location = item.get("location") or {}
                project_key = (
                    location.get("projectKey")
                    or location.get("projectName")
                    or ""
                )
                board_id = item.get("id")
                name = (item.get("name") or f"Board {board_id}").strip()
                boards.append(
                    {
                        "id": board_id,
                        "name": name,
                        "type": item.get("type") or "",
                        "project_key": project_key,
                        "url": board_url(settings, board_id, str(project_key)),
                    }
                )
            total = int(data.get("total") or 0)
            start += len(values)
            if not values or start >= total:
                break

    boards.sort(key=lambda b: (b.get("name") or "").lower())
    return boards
