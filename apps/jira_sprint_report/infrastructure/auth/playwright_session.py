from __future__ import annotations

import json
import os
import time
from pathlib import Path

from jira_sprint_report.infrastructure.config import (
    BROWSER_PROFILE_DIR,
    COOKIES_PATH,
    PLAYWRIGHT_BROWSERS_DIR,
    STORAGE_STATE_PATH,
)


def _ensure_browsers_path() -> None:
    """Keep Chromium in the project dir (avoid ephemeral sandbox caches)."""
    PLAYWRIGHT_BROWSERS_DIR.mkdir(parents=True, exist_ok=True)
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(PLAYWRIGHT_BROWSERS_DIR)


IMPORTANT_COOKIE_NAMES = {
    "tenant.session.token",
    "atlassian.xsrf.token",
    "cloud.session.token",
    "JSESSIONID",
}


def cookies_to_header(cookies: list[dict]) -> str:
    pairs: list[str] = []
    seen: set[str] = set()
    prioritized = [c for c in cookies if c.get("name") in IMPORTANT_COOKIE_NAMES]
    rest = [c for c in cookies if c.get("name") not in IMPORTANT_COOKIE_NAMES]
    for cookie in prioritized + rest:
        name = cookie.get("name")
        value = cookie.get("value")
        if not name or value is None or name in seen:
            continue
        seen.add(name)
        pairs.append(f"{name}={value}")
    return "; ".join(pairs)


def _has_session(cookies: list[dict]) -> bool:
    names = {c.get("name") for c in cookies}
    return bool(names & {"tenant.session.token", "cloud.session.token"})


def save_session(cookies: list[dict], storage_state: dict | None = None) -> str:
    header = cookies_to_header(cookies)
    if not header:
        raise RuntimeError("Nenhum cookie capturado após o login.")

    COOKIES_PATH.parent.mkdir(parents=True, exist_ok=True)
    COOKIES_PATH.write_text(
        json.dumps(
            {
                "cookie_header": header,
                "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "cookie_names": [c.get("name") for c in cookies],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    # Also keep a plain header file for quick reads
    COOKIES_PATH.with_suffix(".txt").write_text(header, encoding="utf-8")

    if storage_state is not None:
        STORAGE_STATE_PATH.write_text(json.dumps(storage_state), encoding="utf-8")

    return header


def load_saved_cookie(path: Path | None = None) -> str:
    """Load cookie header extracted by Playwright login."""
    json_path = path or COOKIES_PATH
    txt_path = json_path.with_suffix(".txt")

    if json_path.exists():
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("cookie_header"):
                return str(data["cookie_header"]).strip()
            if isinstance(data, str):
                return data.strip()
        except json.JSONDecodeError:
            # Legacy: raw cookie string in .cookies.json
            raw = json_path.read_text(encoding="utf-8").strip()
            if raw and not raw.startswith("{"):
                return raw

    if txt_path.exists():
        return txt_path.read_text(encoding="utf-8").strip()
    return ""


def clear_saved_session() -> None:
    for path in (COOKIES_PATH, COOKIES_PATH.with_suffix(".txt"), STORAGE_STATE_PATH):
        if path.exists():
            path.unlink()


def login_and_capture(
    base_url: str,
    board_url: str,
    headless: bool = False,
    timeout_ms: int = 300_000,
) -> str:
    """Open Chromium, wait for you to log in, extract session cookies automatically."""
    _ensure_browsers_path()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright não instalado. Rode: pip install playwright && playwright install chromium"
        ) from exc

    chrome = PLAYWRIGHT_BROWSERS_DIR / "chromium-1248" / "chrome-linux64" / "chrome"
    if not chrome.exists():
        # Fallback: any chromium-* folder
        matches = sorted(PLAYWRIGHT_BROWSERS_DIR.glob("chromium-*/chrome-linux64/chrome"))
        chrome = matches[-1] if matches else chrome
    if not chrome.exists():
        raise RuntimeError(
            "Chromium do Playwright não encontrado. Rode no projeto:\n"
            "  PLAYWRIGHT_BROWSERS_PATH=.playwright-browsers playwright install chromium"
        )

    target = board_url or base_url
    BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + (timeout_ms / 1000)

    with sync_playwright() as p:
        # Persistent profile keeps Atlassian login between runs
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(BROWSER_PROFILE_DIR),
            executable_path=str(chrome),
            headless=headless,
            viewport={"width": 1400, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(target, wait_until="domcontentloaded")

        # Poll cookies via Playwright API (sees HttpOnly tokens that JS cannot)
        while time.time() < deadline:
            cookies = context.cookies()
            if _has_session(cookies):
                # Confirm we're past identity login page
                url = page.url.lower()
                if "id.atlassian.com" in url or "/login" in url:
                    page.wait_for_timeout(1500)
                    continue
                # Settle on board to refresh any product cookies
                try:
                    if board_url and "boards/" not in page.url:
                        page.goto(board_url, wait_until="domcontentloaded", timeout=60_000)
                    page.wait_for_timeout(2500)
                except Exception:
                    page.wait_for_timeout(1500)
                cookies = context.cookies()
                if _has_session(cookies):
                    storage = context.storage_state()
                    header = save_session(cookies, storage)
                    context.close()
                    return header
            page.wait_for_timeout(1500)

        context.close()

    raise RuntimeError(
        "Tempo esgotado esperando login. Abra de novo, faça login no Jira e aguarde a board carregar."
    )


def ensure_cookie(
    base_url: str,
    board_url: str,
    force_login: bool = False,
) -> str:
    """Return a usable cookie; open login window only if missing or forced."""
    if not force_login:
        existing = load_saved_cookie()
        if existing and ("tenant.session.token=" in existing or "cloud.session.token=" in existing):
            return existing
    return login_and_capture(base_url, board_url)
