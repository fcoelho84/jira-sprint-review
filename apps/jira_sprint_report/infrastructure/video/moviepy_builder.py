from __future__ import annotations

from pathlib import Path

SLIDE_W = 1920
SLIDE_H = 1080
SIDES = ("left", "right", "bottom", "top")


def build_video(
    slide_pngs: list[Path],
    audio_files: list[Path],
    output_path: Path,
    fps: int = 24,
) -> Path:
    if len(slide_pngs) != len(audio_files):
        raise ValueError(
            f"Quantidade de slides ({len(slide_pngs)}) != áudios ({len(audio_files)})"
        )
    if not slide_pngs:
        raise ValueError("Nenhum slide para montar o vídeo.")

    try:
        from moviepy import (
            AudioFileClip,
            CompositeVideoClip,
            ImageClip,
            concatenate_videoclips,
            vfx,
        )
    except ImportError:
        from moviepy.editor import (  # type: ignore
            AudioFileClip,
            CompositeVideoClip,
            ImageClip,
            concatenate_videoclips,
        )
        from moviepy.editor import vfx  # type: ignore

    clips = []
    audios_open = []
    try:
        for idx, (png, mp3) in enumerate(zip(slide_pngs, audio_files)):
            audio = AudioFileClip(str(mp3))
            audios_open.append(audio)
            duration = max(float(audio.duration or 1.0), 1.2)

            fade = min(0.45, duration / 5.0)
            slide_in = min(0.55, duration / 4.0)
            side = SIDES[idx % len(SIDES)]
            # Alternate zoom-in vs zoom-out for variety
            zoom_in = idx % 2 == 0
            zoom_amount = 0.07

            base = ImageClip(str(png)).with_duration(duration).with_fps(fps)

            def _scale(t: float, d: float = duration, zin: bool = zoom_in, amt: float = zoom_amount) -> float:
                p = 0.0 if d <= 0 else max(0.0, min(1.0, t / d))
                if zin:
                    return 1.0 + amt * p
                return (1.0 + amt) - amt * p

            zooming = base.resized(_scale).with_position("center")
            motion = (
                CompositeVideoClip([zooming], size=(SLIDE_W, SLIDE_H))
                .with_duration(duration)
                .with_fps(fps)
                .with_audio(audio)
            )

            effects = [
                vfx.SlideIn(slide_in, side),
                vfx.FadeIn(fade),
                vfx.FadeOut(fade),
            ]
            # Soften first/last slides with a bit more fade
            if idx == 0:
                effects[1] = vfx.FadeIn(min(0.7, fade + 0.25))
            if idx == len(slide_pngs) - 1:
                effects[2] = vfx.FadeOut(min(0.8, fade + 0.3))

            motion = motion.with_effects(effects)
            clips.append(motion)

        final = concatenate_videoclips(clips, method="compose")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        final.write_videofile(
            str(output_path),
            fps=fps,
            codec="libx264",
            audio_codec="aac",
            threads=4,
            logger=None,
            preset="medium",
        )
        final.close()
    finally:
        for clip in clips:
            try:
                clip.close()
            except Exception:
                pass
        for audio in audios_open:
            try:
                audio.close()
            except Exception:
                pass

    return output_path
