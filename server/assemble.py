"""ffmpeg assembly — concat certified clips into one episode. Local, zero tokens.

Each input is scaled+padded to a common frame and re-encoded, so clips that differ
in resolution (a draft-tier fallback beside promoted finals) still concatenate
cleanly. No audio (wan t2v produces none). This is the AssembleFn the pipeline injects.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class AssembleError(RuntimeError):
    pass


def assemble(clip_paths: list[str], out_path: str, *, width: int = 1280, height: int = 720) -> str:
    if not clip_paths:
        raise AssembleError("no clips to assemble")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise AssembleError("ffmpeg not found on PATH")

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    cmd = [ffmpeg, "-y"]
    for p in clip_paths:
        cmd += ["-i", str(p)]

    n = len(clip_paths)
    # Normalize each stream to width x height (letterbox), reset SAR, then concat.
    norm = "".join(
        f"[{i}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1[v{i}];"
        for i in range(n)
    )
    concat = "".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[outv]"
    cmd += ["-filter_complex", norm + concat, "-map", "[outv]",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)]

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise AssembleError(f"ffmpeg failed: {proc.stderr[-500:]}")
    if not out.exists() or out.stat().st_size == 0:
        raise AssembleError("ffmpeg produced no output")
    return str(out)
