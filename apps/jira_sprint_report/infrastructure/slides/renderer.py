from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Inches

from jira_sprint_report.application.report_structurer import strip_markdown
from jira_sprint_report.domain.models import SlideSpec, SlideTheme, StructuredReport

SLIDE_W = 1920
SLIDE_H = 1080


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf" if bold else "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


def _clip(text: str, max_len: int) -> str:
    text = strip_markdown(text or "").strip()
    if len(text) <= max_len:
        return text
    return text[: max(0, max_len - 1)].rstrip(" ,;:-") + "…"


def _prepare_copy(spec: SlideSpec) -> tuple[str, list[str], bool]:
    has_images = bool(spec.image_paths) and spec.kind == "content"
    title_max = 72 if has_images else 96
    bullet_max = 100 if has_images else 130
    max_bullets = 4 if has_images else 5
    if spec.kind == "summary":
        max_bullets = 8 if not has_images else 6
        bullet_max = 90 if has_images else 110

    title = _clip(spec.title, title_max)
    bullets = [_clip(b, bullet_max) for b in spec.bullets[:max_bullets]]
    if len(spec.bullets) > max_bullets:
        extra = len(spec.bullets) - max_bullets
        bullets.append(_clip(f"+{extra} item(ns) no relatório completo", 80))
    return title, bullets, has_images


def _wrap(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
    max_lines: int | None = None,
) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        trial = f"{current} {word}"
        if draw.textlength(trial, font=font) <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
            if max_lines is not None and len(lines) >= max_lines:
                last = lines[-1]
                while draw.textlength(last + "…", font=font) > max_width and len(last) > 1:
                    last = last[:-1]
                lines[-1] = last.rstrip() + "…"
                return lines
    lines.append(current)
    if max_lines is not None and len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while draw.textlength(last + "…", font=font) > max_width and len(last) > 1:
            last = last[:-1]
        lines[-1] = last.rstrip() + "…"
    return lines


def _load_illustration(path: Path) -> Image.Image | None:
    try:
        img = Image.open(path)
        img = ImageOps.exif_transpose(img)
        return img.convert("RGB")
    except Exception:
        return None


def _paste_illustrations(
    canvas: Image.Image,
    image_paths: list,
    box: tuple[int, int, int, int],
    card: tuple[int, int, int],
) -> None:
    paths = [Path(p) for p in image_paths if p][:2]
    loaded = [im for im in (_load_illustration(p) for p in paths) if im is not None]
    if not loaded:
        return

    left, top, right, bottom = box
    height = max(bottom - top, 1)
    gap = 16

    if len(loaded) == 1:
        slots = [(left, top, right, bottom)]
    else:
        mid = top + (height - gap) // 2
        slots = [
            (left, top, right, mid),
            (left, mid + gap, right, bottom),
        ]

    for image, (sl, st, sr, sb) in zip(loaded, slots):
        slot_w = max(sr - sl, 1)
        slot_h = max(sb - st, 1)
        fitted = ImageOps.contain(image, (slot_w, slot_h))
        x = sl + (slot_w - fitted.width) // 2
        y = st + (slot_h - fitted.height) // 2
        frame = Image.new("RGB", (fitted.width + 8, fitted.height + 8), card)
        frame.paste(fitted, (4, 4))
        canvas.paste(frame, (max(sl, x - 4), max(st, y - 4)))


def render_slide_png(
    spec: SlideSpec,
    path: Path,
    theme: SlideTheme | None = None,
) -> Path:
    theme = theme or SlideTheme()
    colors = theme.resolved()
    bg, title_c, body_c, accent, card = (
        colors["bg"],
        colors["title"],
        colors["body"],
        colors["accent"],
        colors["card"],
    )

    img = Image.new("RGB", (SLIDE_W, SLIDE_H), bg)
    draw = ImageDraw.Draw(img)

    draw.rectangle([0, 0, 16, SLIDE_H], fill=accent)
    draw.rectangle([0, 0, SLIDE_W, 8], fill=accent)

    title, bullets, has_images = _prepare_copy(spec)

    dense = len(bullets) >= 5 or sum(len(b) for b in bullets) > 380
    title_size = 52 if spec.kind == "cover" else (36 if dense or has_images else 44)
    body_size = 24 if dense or has_images else 30
    title_font = _font(title_size, bold=True)
    body_font = _font(body_size)
    small_font = _font(22)

    margin_x = 100
    text_max_w = 980 if has_images else SLIDE_W - margin_x * 2
    footer_y = SLIDE_H - 70
    line_h = 48 if dense or has_images else 56
    bullet_line_h = 34 if dense or has_images else 40

    y = 100 if spec.kind != "cover" else 280
    for line in _wrap(draw, title, title_font, text_max_w, max_lines=2):
        draw.text((margin_x, y), line, font=title_font, fill=title_c)
        y += line_h

    y += 28
    if spec.kind == "cover":
        for line in bullets:
            if y > footer_y - 40:
                break
            for wrapped in _wrap(draw, line, body_font, text_max_w, max_lines=2):
                draw.text((margin_x, y), wrapped, font=body_font, fill=body_c)
                y += bullet_line_h + 4
                if y > footer_y - 40:
                    break
    else:
        for bullet in bullets:
            if y > footer_y - 50:
                break
            wrapped = _wrap(draw, bullet, body_font, text_max_w - 60, max_lines=3)
            block_h = 18 + len(wrapped) * bullet_line_h
            if y + block_h > footer_y - 20:
                break
            draw.rounded_rectangle(
                [margin_x - 10, y - 6, margin_x + text_max_w + 10, y + block_h],
                radius=12,
                fill=card,
            )
            draw.ellipse([margin_x + 8, y + 10, margin_x + 22, y + 24], fill=accent)
            ty = y + 6
            for wline in wrapped:
                draw.text((margin_x + 40, ty), wline, font=body_font, fill=body_c)
                ty += bullet_line_h
            y += block_h + 14

    if has_images:
        _paste_illustrations(
            img,
            list(spec.image_paths),
            box=(1120, 140, SLIDE_W - 80, footer_y - 20),
            card=card,
        )

    draw.text(
        (margin_x, footer_y),
        "Sprint Report · Rovo",
        font=small_font,
        fill=body_c,
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "PNG")
    return path


def export_pngs(
    report: StructuredReport,
    out_dir: Path,
    theme: SlideTheme | None = None,
) -> list[Path]:
    theme = theme or SlideTheme()
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for i, spec in enumerate(report.slides, start=1):
        path = out_dir / f"slide-{i:02d}.png"
        render_slide_png(spec, path, theme=theme)
        paths.append(path)
    return paths


def build_pptx(
    report: StructuredReport,
    path: Path,
    png_paths: list[Path] | None = None,
    theme: SlideTheme | None = None,
) -> Path:
    """Build PPTX by embedding the rendered PNGs (avoids LibreOffice text overlap)."""
    theme = theme or SlideTheme()
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    paths = [Path(p) for p in (png_paths or [])]
    if not paths:
        tmp = path.parent / "_pptx_pngs"
        paths = export_pngs(report, tmp, theme=theme)

    blank = prs.slide_layouts[6]
    bg = theme.resolved()["bg"]
    for idx, png in enumerate(paths):
        slide = prs.slides.add_slide(blank)
        if png.exists():
            slide.shapes.add_picture(
                str(png),
                Inches(0),
                Inches(0),
                width=prs.slide_width,
                height=prs.slide_height,
            )
        else:
            shape = slide.shapes.add_shape(1, Inches(0), Inches(0), prs.slide_width, prs.slide_height)
            shape.fill.solid()
            shape.fill.fore_color.rgb = RGBColor(*bg)
            shape.line.fill.background()

        if idx < len(report.slides):
            notes = slide.notes_slide.notes_text_frame
            notes.text = strip_markdown(report.slides[idx].narration)

    path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(path)
    return path
