"""ffmpeg assembly — concat certified clips into one episode. Local, zero tokens.

Every segment must carry an audio stream: concat fails outright on a graph mixing silent
and sounded inputs, so a shot with no narration gets generated silence.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

SAMPLE_RATE = 44100
AUDIO_CODEC = ["-c:a", "aac", "-b:a", "128k", "-ar", str(SAMPLE_RATE), "-ac", "2"]


class AssembleError(RuntimeError):
    pass


def _ffmpeg() -> str:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise AssembleError("ffmpeg not found on PATH")
    return ffmpeg


def _run(cmd: list[str], what: str) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise AssembleError(f"{what} failed: {proc.stderr[-500:]}")


def mux_narration(clip_path: str, audio_path: str | None, out_path: str) -> str:
    """Give one clip exactly one audio stream: the narration, or silence.

    `apad` before `-shortest` is load-bearing — without it, short narration truncates the VIDEO.
    """
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [_ffmpeg(), "-y", "-i", str(clip_path)]
    if audio_path:
        cmd += ["-i", str(audio_path), "-filter_complex", "[1:a]apad[a]", "-map", "0:v:0", "-map", "[a]"]
    else:
        cmd += ["-f", "lavfi", "-i", f"anullsrc=channel_layout=stereo:sample_rate={SAMPLE_RATE}",
                "-map", "0:v:0", "-map", "1:a:0"]
    cmd += ["-c:v", "copy", *AUDIO_CODEC, "-shortest", str(out)]
    _run(cmd, "ffmpeg mux")
    if not out.exists() or out.stat().st_size == 0:
        raise AssembleError("ffmpeg mux produced no output")
    return str(out)


def assemble(clip_paths: list[str], out_path: str, *, width: int = 1280, height: int = 720,
             audio_paths: list[str | None] | None = None) -> str:
    if not clip_paths:
        raise AssembleError("no clips to assemble")
    ffmpeg = _ffmpeg()

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    n = len(clip_paths)

    # Must give every segment sound BEFORE concatenating; one filter_complex over mixed
    # sounded/silent inputs fails on the first silent one.
    if audio_paths is not None:
        if len(audio_paths) != n:
            raise AssembleError(f"audio_paths has {len(audio_paths)} entries for {n} clips")
        staged = out.parent / "_audio"
        staged.mkdir(parents=True, exist_ok=True)
        clip_paths = [mux_narration(c, a, str(staged / f"seg{i}.mp4"))
                      for i, (c, a) in enumerate(zip(clip_paths, audio_paths))]

    cmd = [ffmpeg, "-y"]
    for p in clip_paths:
        cmd += ["-i", str(p)]

    # Normalize each stream to width x height (letterbox), reset SAR, then concat.
    norm = "".join(
        f"[{i}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1[v{i}];"
        for i in range(n)
    )
    if audio_paths is None:
        concat = "".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[outv]"
        cmd += ["-filter_complex", norm + concat, "-map", "[outv]"]
    else:
        # Must resample every track to one rate/layout — concat refuses mismatched inputs.
        norm += "".join(f"[{i}:a]aresample={SAMPLE_RATE},aformat=channel_layouts=stereo[a{i}];"
                        for i in range(n))
        concat = ("".join(f"[v{i}][a{i}]" for i in range(n))
                  + f"concat=n={n}:v=1:a=1[outv][outa]")
        cmd += ["-filter_complex", norm + concat, "-map", "[outv]", "-map", "[outa]", *AUDIO_CODEC]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)]

    _run(cmd, "ffmpeg")
    if not out.exists() or out.stat().st_size == 0:
        raise AssembleError("ffmpeg produced no output")
    return str(out)
