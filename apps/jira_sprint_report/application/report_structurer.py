from __future__ import annotations

import re

from jira_sprint_report.domain.models import SlideSpec, StructuredReport


_ISSUE_RE = re.compile(
    r"(?:^|\n)\s*(?:#{1,3}\s*)?"
    r"(?:\[\s*(?P<key1>[A-Z][A-Z0-9]+-\d+)\s*\]\([^)]+\)|"
    r"\*\*(?P<key2>[A-Z][A-Z0-9]+-\d+)\*\*|"
    r"(?P<key3>[A-Z][A-Z0-9]+-\d+))"
    r"(?:\s*[:\-–—]\s*|\s+)(?P<title>[^\n]+)",
    re.MULTILINE,
)


def strip_markdown(text: str) -> str:
    """Turn Markdown into plain text suitable for PNG/PPTX rendering."""
    if not text:
        return ""
    out = text
    # links [label](url) -> label
    out = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", out)
    # images ![alt](url) -> alt
    out = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", out)
    # bold/italic
    out = re.sub(r"\*\*\*(.+?)\*\*\*", r"\1", out)
    out = re.sub(r"\*\*(.+?)\*\*", r"\1", out)
    out = re.sub(r"__(.+?)__", r"\1", out)
    out = re.sub(r"(?<!\w)\*(.+?)\*(?!\w)", r"\1", out)
    out = re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"\1", out)
    # inline code / fences
    out = re.sub(r"`{1,3}([^`]*)`{1,3}", r"\1", out)
    # headings / quotes
    out = re.sub(r"(?m)^#{1,6}\s*", "", out)
    out = re.sub(r"(?m)^>\s*", "", out)
    # leftover emphasis junk
    out = out.replace("**", "").replace("__", "")
    out = re.sub(r"[ \t]+", " ", out)
    return out.strip()


def _issue_key(match: re.Match[str]) -> str:
    return match.group("key1") or match.group("key2") or match.group("key3") or ""


def _split_sections(markdown: str) -> list[tuple[str, str]]:
    parts = re.split(r"(?m)^(#{1,3}\s+.+)$", markdown.strip())
    if len(parts) == 1:
        return [("Relatório", markdown.strip())]

    sections: list[tuple[str, str]] = []
    if parts[0].strip():
        sections.append(("Introdução", parts[0].strip()))
    for i in range(1, len(parts), 2):
        heading = strip_markdown(re.sub(r"^#+\s*", "", parts[i]))
        body = parts[i + 1].strip() if i + 1 < len(parts) else ""
        sections.append((heading, body))
    return sections


def _bullets_from_text(text: str, limit: int = 8) -> list[str]:
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        line = re.sub(r"^[-*•]\s+", "", line)
        line = re.sub(r"^\d+\.\s+", "", line)
        # Keep "Para falar" out of slide bullets — it goes to narration only
        if re.match(r"(?i)^(?:para falar|narra[cç][aã]o|roteiro)\s*:", line):
            continue
        if re.match(r"(?i)^encerramento\s+para\s+falar\s*:", line):
            continue
        # Never show Jira status on slides
        if re.match(r"(?i)^status\s*:", line):
            continue
        line = strip_markdown(line)
        if not line:
            continue
        if len(line) > 180:
            line = line[:177] + "..."
        lines.append(line)
        if len(lines) >= limit:
            break
    if not lines and text.strip():
        chunk = strip_markdown(" ".join(text.split()))
        lines = [chunk[:180] + ("..." if len(chunk) > 180 else "")]
    return lines


_SPEAK_LINE_RE = re.compile(
    r"(?im)^\s*(?:[-*•]\s*)?(?:para falar|narra[cç][aã]o|roteiro)\s*:\s*(.+)$"
)
_CLOSING_SPEAK_RE = re.compile(
    r"(?is)encerramento\s+para\s+falar\s*:\s*(.+?)(?:\n\s*\n|\Z)"
)


def _extract_speak_line(block: str) -> str:
    matches = list(_SPEAK_LINE_RE.finditer(block))
    if not matches:
        return ""
    return strip_markdown(matches[-1].group(1))


def _extract_closing_speak(text: str) -> str:
    match = _CLOSING_SPEAK_RE.search(text)
    if not match:
        return ""
    return strip_markdown(re.sub(r"\s+", " ", match.group(1)).strip())


def _field_from_bullets(bullets: list[str], *prefixes: str) -> str:
    for bullet in bullets:
        lower = bullet.lower()
        for prefix in prefixes:
            if lower.startswith(prefix):
                return strip_markdown(bullet.split(":", 1)[-1]).strip()
    return ""


def _narration_from_slide(
    title: str,
    bullets: list[str],
    speak: str = "",
    group: str = "delivery",
) -> str:
    """Build a spoken, human narration for TTS."""
    title = strip_markdown(title)
    if speak:
        return speak if speak.endswith((".", "!", "?")) else f"{speak}."

    pedido = _field_from_bullets(bullets, "o que foi pedido", "pedido")
    solucao = _field_from_bullets(bullets, "solução", "solucao", "solução / comentários")
    motivo = _field_from_bullets(bullets, "motivo da renegociação", "motivo")

    key_match = re.match(r"^([A-Z][A-Z0-9]+-\d+)\s*[—\-–:]\s*(.+)$", title)
    if key_match:
        key, short = key_match.group(1), key_match.group(2).strip()
        if group == "renegotiation":
            parts = [f"A {key}, sobre {short}, saiu da sprint."]
            if motivo:
                parts.append(f"Motivo: {motivo[0].lower() + motivo[1:] if motivo else motivo}")
                if not parts[-1].endswith("."):
                    parts[-1] += "."
            return " ".join(parts)
        if group == "mid_sprint":
            parts = [f"A {key} entrou depois do início da sprint: {short}."]
        else:
            parts = [f"Na {key}, trabalhamos em {short}."]
        if pedido:
            parts.append(f"O pedido era {pedido[0].lower() + pedido[1:] if pedido else pedido}")
            if not parts[-1].endswith("."):
                parts[-1] += "."
        if solucao:
            parts.append(f"No fim, {solucao[0].lower() + solucao[1:] if solucao else solucao}")
            if not parts[-1].endswith("."):
                parts[-1] += "."
        return " ".join(parts)

    clean_bullets = [strip_markdown(b) for b in bullets if b]
    if not clean_bullets:
        return f"Agora, {title}."
    body = ". ".join(clean_bullets[:4])
    if not body.endswith("."):
        body += "."
    return f"Sobre {title}: {body}"


def _section_kind(heading: str) -> str | None:
    h = strip_markdown(heading).lower()
    if re.search(r"renegocia", h):
        return "renegotiation"
    if re.search(r"entraram\s+ap[oó]s|ap[oó]s\s+o\s+in[ií]cio|meio\s+da\s+sprint|mid[- ]?sprint", h):
        return "mid_sprint"
    if re.search(r"entrega|planejamento|compromet", h):
        return "delivery"
    if re.search(r"encerramento", h):
        return "closing"
    return None


def _partition_by_section(text: str) -> dict[str, str]:
    """Split report markdown into delivery / mid_sprint / renegotiation bodies."""
    sections = _split_sections(text)
    buckets = {"delivery": [], "mid_sprint": [], "renegotiation": [], "other": []}
    current = "other"
    for heading, body in sections:
        kind = _section_kind(heading)
        if kind == "closing":
            continue
        if kind:
            current = kind
            buckets[current].append(body)
        else:
            buckets[current].append(f"{heading}\n{body}".strip())
    return {k: "\n\n".join(v).strip() for k, v in buckets.items() if v}


def _issues_in_text(text: str) -> list[tuple[re.Match[str], str]]:
    """Return (match, block) for each issue in text."""
    matches = list(_ISSUE_RE.finditer(text))
    out: list[tuple[re.Match[str], str]] = []
    for idx, match in enumerate(matches):
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        out.append((match, text[start:end].strip()))
    return out


def _append_issue_slides(
    slides: list[SlideSpec],
    section_text: str,
    group: str,
) -> int:
    items = _issues_in_text(section_text)
    for match, block in items:
        key = _issue_key(match)
        title = strip_markdown(match.group("title"))
        body = block.split("\n", 1)[1] if "\n" in block else ""
        speak = _extract_speak_line(block)
        bullets = _bullets_from_text(body, limit=7)
        if not bullets:
            bullets = ["Detalhes no relatório completo."]
        # Prefer motivo line first for renegotiations
        if group == "renegotiation":
            motivo = _field_from_bullets(bullets, "motivo da renegociação", "motivo")
            if motivo and not any(b.lower().startswith("motivo") for b in bullets):
                bullets = [f"Motivo da renegociação: {motivo}"] + bullets
        slide_title = f"{key} — {title[:60]}"
        slides.append(
            SlideSpec(
                title=slide_title,
                bullets=bullets,
                narration=_narration_from_slide(
                    slide_title, bullets, speak=speak, group=group
                ),
                kind="content",
                issue_key=key,
            )
        )
    return len(items)


def structure_report(markdown: str, sprint_label: str = "Sprint atual") -> StructuredReport:
    text = markdown.strip()
    buckets = _partition_by_section(text)
    # Fallback: if no section headings, treat whole text as deliveries
    if not any(buckets.get(k) for k in ("delivery", "mid_sprint", "renegotiation")):
        buckets = {"delivery": text, "mid_sprint": "", "renegotiation": ""}

    delivery_text = buckets.get("delivery", "")
    mid_text = buckets.get("mid_sprint", "")
    reno_text = buckets.get("renegotiation", "")

    n_delivery = len(_issues_in_text(delivery_text))
    n_mid = len(_issues_in_text(mid_text))
    n_reno = len(_issues_in_text(reno_text))

    cover_bullets = [sprint_label]
    if n_delivery:
        cover_bullets.append(f"{n_delivery} entrega(s) do planejamento")
    if n_mid:
        cover_bullets.append(f"{n_mid} entraram após o início")
    if n_reno:
        cover_bullets.append(f"{n_reno} renegociação(ões)")

    slides: list[SlideSpec] = [
        SlideSpec(
            title="Relatório da Sprint",
            bullets=cover_bullets,
            narration=(
                f"Oi, pessoal. Vamos ao relatório da {sprint_label}. "
                "Vou separar o que estava no planejamento, o que entrou no meio da sprint "
                "e o que foi renegociado."
            ),
            kind="cover",
        )
    ]

    def add_group(section_title: str, body: str, group: str, intro: str) -> None:
        count = len(_issues_in_text(body))
        if count == 0 and group != "delivery":
            return
        if count == 0 and group == "delivery" and not body.strip():
            return
        summary_items = []
        for m, _ in _issues_in_text(body)[:10]:
            summary_items.append(
                f"{_issue_key(m)}: {strip_markdown(m.group('title'))[:80]}"
            )
        if not summary_items and body.strip() and "nenhuma" in body.lower():
            slides.append(
                SlideSpec(
                    title=section_title,
                    bullets=["Nenhum item neste grupo"],
                    narration=intro,
                    kind="summary",
                )
            )
            return
        slides.append(
            SlideSpec(
                title=section_title,
                bullets=summary_items
                + ([f"... e mais {count - 10}"] if count > 10 else []),
                narration=intro,
                kind="summary",
            )
        )
        _append_issue_slides(slides, body, group=group)

    add_group(
        "Entregas do planejamento",
        delivery_text,
        "delivery",
        (
            f"Começando pelas entregas do planejamento: {n_delivery} item(ns). "
            "Esses já estavam no escopo no início da sprint."
            if n_delivery
            else "Não houve entregas classificadas no planejamento."
        ),
    )
    add_group(
        "Entraram após o início",
        mid_text,
        "mid_sprint",
        (
            f"Agora o que entrou depois do início da sprint: {n_mid} item(ns)."
            if n_mid
            else "Nada entrou após o início da sprint."
        ),
    )
    add_group(
        "Renegociações",
        reno_text,
        "renegotiation",
        (
            f"Por fim, as renegociações: {n_reno} item(ns) saíram da sprint."
            if n_reno
            else "Sem renegociações nesta sprint."
        ),
    )

    # Absolute fallback if partitioning found nothing usable
    if len(slides) == 1:
        for heading, body in _split_sections(text)[:12]:
            if re.match(r"(?i)^encerramento", heading):
                continue
            bullets = _bullets_from_text(body, limit=7)
            speak = _extract_speak_line(body)
            slides.append(
                SlideSpec(
                    title=strip_markdown(heading)[:80],
                    bullets=bullets or ["Ver relatório completo."],
                    narration=_narration_from_slide(heading, bullets, speak=speak),
                    kind="content",
                )
            )

    closing_speak = _extract_closing_speak(text)
    slides.append(
        SlideSpec(
            title="Encerramento",
            bullets=["Obrigado", "Dúvidas e próximos passos"],
            narration=closing_speak
            or (
                "Era isso para esta sprint. "
                "Obrigado, pessoal — se alguém quiser detalhar algum item ou tirar dúvida, é só falar."
            ),
            kind="closing",
        )
    )

    return StructuredReport(title=f"Relatório — {sprint_label}", markdown=text, slides=slides)
