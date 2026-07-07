"""Demo-mode runtime — the whole pipeline offline, zero quota.

Real Tier-A CV and real ffmpeg assembly run on SYNTHETIC clips generated locally,
so the SPA and Playwright e2e exercise genuine behavior without spending video
quota. It also plants the kill-shot: shot 1 asserts a rightward camera pan, but
the first synthetic draft is static (simulating the model failing to move the
camera) -> Tier-A catches it -> repair injects a [retake] directive -> the second
synthetic draft actually pans right -> it passes and promotes. That's the demo's
spine, reproducible with no network.

Enable with DAILIES_DEMO=1 (see server.app.create_production_app).
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

from server.assemble import assemble
from server.metrics import LedgerWriter
from server.pipeline import Config, Deps
from server.specs import AssertionResult, AssertionType, ShotSpec, Status, Tier
from server.store import Store
from server.tier_a import run_tier_a
from server.wan import WanResult

_FOURCC = cv2.VideoWriter_fourcc(*"mp4v")

# Fixed storyboard; shot 1 is the planted kill-shot (asserts a right pan).
_DEMO_SHOTS = [
    {"prompt": "establishing wide shot of a lonely lighthouse at dusk, waves below, still locked-off camera",
     "assertions": []},
    {"prompt": "the keeper climbs the spiral staircase, camera slowly pans right to follow him",
     "subject": "the lighthouse keeper",
     "assertions": [{"type": "camera_motion", "params": {"direction": "right"}},
                    {"type": "identity_consistent", "params": {"subject": "the lighthouse keeper"}}]},
    {"prompt": "close-up of the great lamp igniting, warm light flooding the glass room",
     "assertions": [{"type": "action_completed", "params": {"action": "the lamp ignites and glows"}}]},
]


def _usage(pin=180, pout=60):
    return SimpleNamespace(prompt_tokens=pin, completion_tokens=pout, total_tokens=pin + pout)


def _direction_from_prompt(prompt: str) -> str:
    # Only honor a pan once repair has issued a [retake] directive (first drafts stay static).
    if "[retake]" not in prompt:
        return "static"
    for d in ("right", "left", "up", "down"):
        if f"pan {d}" in prompt or f"pans {d}" in prompt:
            return d
    return "static"


def _texture(h: int, w_total: int) -> np.ndarray:
    rng = np.random.default_rng(7)
    tex = (rng.random((h, w_total)) * 200 + 30).astype(np.uint8)  # mean well inside [25,235]
    tex = cv2.GaussianBlur(tex, (0, 0), 2.0)
    return cv2.cvtColor(tex, cv2.COLOR_GRAY2BGR)


def _write_clip(path: Path, direction: str, w=320, h=180, n=40, fps=8) -> None:
    """5s clip (n/fps). A pan slides a crop window over a wide texture; static repeats one window."""
    slide = 2
    total = w + n * slide + 4
    tex = _texture(h, total)
    vw = cv2.VideoWriter(str(path), _FOURCC, fps, (w, h))
    for i in range(n):
        if direction == "right":
            x = i * slide                      # window slides right -> content left -> camera right
        elif direction == "left":
            x = (n - i) * slide
        else:
            x = total // 2 - w // 2            # static
        x = max(0, min(x, total - w))
        vw.write(tex[:, x:x + w])
    vw.release()


def _write_still(path: Path, w=320, h=180) -> None:
    cv2.imwrite(str(path), _texture(h, w)[:, :w])


class _DemoGen:
    """Fake generators that write real synthetic media into the cache dir."""

    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _key(self, prompt: str, model: str) -> str:
        return hashlib.sha1(f"{model}|{prompt}".encode()).hexdigest()[:16]

    def gen_video(self, prompt: str, model: str, negative_prompt: str | None = None) -> WanResult:
        key = self._key(prompt, model)
        path = self.cache_dir / f"{key}.mp4"
        cached = path.exists()
        if not cached:
            _write_clip(path, _direction_from_prompt(prompt))
        return WanResult(status="SUCCEEDED", kind="video", local_path=str(path),
                         from_cache=cached, seconds=0 if cached else 5, latency_ms=120)

    def gen_image(self, prompt: str) -> WanResult:
        key = self._key(prompt, "t2i")
        path = self.cache_dir / f"{key}.png"
        cached = path.exists()
        if not cached:
            _write_still(path)
        return WanResult(status="SUCCEEDED", kind="image", local_path=str(path),
                         from_cache=cached, seconds=0, latency_ms=40)


def _demo_script(premise, pack, max_shots):
    return [dict(s) for s in _DEMO_SHOTS[:max_shots]], _usage()


def _demo_tier_b(video_path, spec: ShotSpec):
    """Deterministic advisory verdicts: identity passes; action is inconclusive (shows verdict UI)."""
    out = []
    for a in spec.assertions:
        if a.tier is not Tier.TIER_B:
            continue
        if a.type is AssertionType.IDENTITY_CONSISTENT:
            out.append(AssertionResult.for_assertion(a, Status.PASS, detail="subject stable across frames"))
        else:
            out.append(AssertionResult.for_assertion(a, Status.INCONCLUSIVE,
                                                     detail="ambiguous — awaiting human verdict"))
    return out


def _demo_repair(spec: ShotSpec, failures):
    # Inject a [retake] directive so the next synthetic draft honors the asserted pan.
    directions = [f.measured.get("detected") for f in failures if f.type is AssertionType.CAMERA_MOTION]
    want = "right"
    for a in spec.assertions:
        if a.type is AssertionType.CAMERA_MOTION:
            want = a.params["direction"]
    return (f"{spec.prompt} [retake] enforce a clear, steady camera that pans {want}", _usage(90, 30))


def build_demo_runtime(data_dir: str = "data/demo") -> "object":
    from server.app import Runtime  # imported here to avoid a cycle at module load

    root = Path(data_dir)
    gen = _DemoGen(root / "cache")
    cfg = Config(data_dir=str(root / "projects"))
    deps = Deps(
        script_fn=_demo_script,
        gen_image_fn=gen.gen_image,
        gen_video_fn=gen.gen_video,
        tier0_fn=lambda spec, still: [],
        tier_a_fn=run_tier_a,          # REAL deterministic CV on the synthetic clips
        tier_b_fn=_demo_tier_b,
        repair_fn=_demo_repair,
        assemble_fn=assemble,          # REAL ffmpeg
        ledger=LedgerWriter(root / "ledger.jsonl"),
    )
    return Runtime(store=Store(str(root / "projects")), deps=deps, cfg=cfg, governor=None)
