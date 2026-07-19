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
import wave
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
                    # Tier-0: asked of the still, before this shot costs a single video second.
                    {"type": "subject_present", "params": {"subject": "the lighthouse keeper"}},
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
    """Designed slate instead of raw noise, with every measured property preserved.

    Three layers, each load-bearing for a Tier-A check:
    - vertical dusk gradient in the brand palette — constant along x, so a sliding
      crop window keeps the same mean luma (flicker-safe) and the dominant colors
      sit near packs/brand_rules.yaml's palette; overall mean ~105, inside every
      pack's brightness bounds;
    - seeded luma grain (blurred) — Farneback needs trackable structure; a clean
      gradient sliding horizontally reads as zero flow and would un-kill the
      planted kill-shot;
    - a faint tiled label, baked into the wide texture so it pans WITH the content
      (a fixed overlay would dilute the mean flow toward static).
    """
    rng = np.random.default_rng(7)
    stops = [(0.0, (250, 247, 245)), (0.45, (255, 95, 11)), (1.0, (22, 17, 14))]  # BGR #f5f7fa -> #0b5fff -> #0e1116, sky over sea
    ys = np.linspace(0.0, 1.0, h)
    col = np.zeros((h, 3), np.float32)
    for c in range(3):
        col[:, c] = np.interp(ys, [s[0] for s in stops], [float(s[1][c]) for s in stops])
    base = np.repeat(col[:, None, :], w_total, axis=1)

    grain = rng.random((h, w_total)).astype(np.float32) * 90 - 45
    grain = cv2.GaussianBlur(grain, (0, 0), 2.0)
    base = np.clip(base + grain[:, :, None], 0, 255).astype(np.uint8)

    overlay = base.copy()
    for x0 in range(20, w_total, 260):
        cv2.putText(overlay, "tier-A: zero tokens", (x0 + 34, 26),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.34, (30, 30, 34), 1, cv2.LINE_AA)
        cv2.putText(overlay, "DAILIES / SYNTHETIC TAKE", (x0, h - 16),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, (255, 255, 255), 1, cv2.LINE_AA)
    return cv2.addWeighted(overlay, 0.35, base, 0.65, 0)


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
        # v2 salt: the key hashes only model|prompt, not clip content, so changing
        # the synthesis (gray noise -> designed slates) must bust pre-existing
        # caches or a warm data dir would replay the old look forever.
        return hashlib.sha1(f"v2|{model}|{prompt}".encode()).hexdigest()[:16]

    def gen_video(self, prompt: str, model: str, negative_prompt: str | None = None) -> WanResult:
        key = self._key(prompt, model)
        path = self.cache_dir / f"{key}.mp4"
        cached = path.exists()
        if not cached:
            _write_clip(path, _direction_from_prompt(prompt))
        return WanResult(status="SUCCEEDED", kind="video", local_path=str(path),
                         from_cache=cached, seconds=0 if cached else 5,
                         cached_seconds=5 if cached else 0, latency_ms=120)

    def gen_patch(self, prompt: str, model: str, frame_path: str) -> WanResult:
        """Frame-anchored repair, offline. The anchor's bytes join the cache key exactly
        as they do in wan.py, so two patches of one shot address different clips."""
        p = Path(frame_path)
        salt = hashlib.sha1(p.read_bytes()).hexdigest()[:12] if p.exists() else "noanchor"
        key = self._key(f"{prompt}|patch|{salt}", model)
        path = self.cache_dir / f"{key}.mp4"
        cached = path.exists()
        if not cached:
            _write_clip(path, _direction_from_prompt(prompt))
        return WanResult(status="SUCCEEDED", kind="video", local_path=str(path),
                         from_cache=cached, seconds=0 if cached else 5,
                         cached_seconds=5 if cached else 0, latency_ms=90)

    def narrate(self, text: str) -> SimpleNamespace:
        """Offline narration: a short, quiet tone standing in for a spoken line.

        Real audio, not a stub — the episode genuinely carries a track, so the assembler's
        mux/concat path is exercised by the e2e at zero quota. Pitch varies with the text
        so consecutive shots are audibly distinct.
        """
        key = self._key(f"{text}|narration", "tts")
        path = self.cache_dir / f"{key}.wav"
        cached = path.exists()
        if not cached:
            rate, seconds = 44100, 1.2
            hz = 220 + (int(hashlib.sha1(text.encode()).hexdigest()[:4], 16) % 6) * 55
            t = np.linspace(0.0, seconds, int(rate * seconds), endpoint=False)
            # Quiet on purpose: this plays under review screenshots and the demo video.
            envelope = np.minimum(1.0, np.minimum(t * 8, (seconds - t) * 8))
            samples = (0.08 * envelope * np.sin(2 * np.pi * hz * t) * 32767).astype("<i2")
            with wave.open(str(path), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(rate)
                w.writeframes(samples.tobytes())
        return SimpleNamespace(status="SUCCEEDED", ok=True, local_path=str(path),
                               from_cache=cached, latency_ms=5, chars=len(text))

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


def _demo_custom_rules(rules):
    """Offline keyword compiler for the demo: maps a few plain phrases to assertions
    (title card, camera pans <dir>). Unrecognized phrases are omitted — mirroring the
    real compiler's 'omit rather than invent' rule — so the flow stays zero-quota."""
    out: list[dict] = []
    for r in rules:
        s = r.lower()
        if "title" in s or "text card" in s or "caption" in s:
            out.append({"type": "title_card_present", "params": {}})
            continue
        if "pan" in s or "camera" in s:
            for d in ("right", "left", "up", "down"):
                if d in s:
                    out.append({"type": "camera_motion", "params": {"direction": d}})
                    break
    return out, _usage(40, 20)


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


def _demo_tier0(spec: ShotSpec, still_path: str):
    """Deterministic Tier-0 verdicts on the pre-render still, zero tokens.

    Demo mode passes Tier-0 on purpose: the planted kill-shot is Tier-A camera_motion,
    and a second failure at the review gate would blur which tier caught what.
    """
    return [
        AssertionResult.for_assertion(
            a, Status.PASS,
            detail=f"{a.params.get('subject', 'subject')} recognizable in the still",
            evidence=[still_path] if still_path else [])
        for a in spec.assertions
        if a.tier is Tier.TIER0
    ]


def _demo_repair(spec: ShotSpec, failures):
    # Inject a [retake] directive so the next synthetic draft honors the asserted pan.
    directions = [f.measured.get("detected") for f in failures if f.type is AssertionType.CAMERA_MOTION]
    want = "right"
    for a in spec.assertions:
        if a.type is AssertionType.CAMERA_MOTION:
            want = a.params["direction"]
    return (f"{spec.prompt} [retake] enforce a clear, steady camera that pans {want}", _usage(90, 30))


def build_demo_runtime(data_dir: str | None = None) -> "object":
    from server.app import Runtime  # imported here to avoid a cycle at module load
    from server.config import settings

    # Follow DATA_DIR so demo output lands where the media route serves from and on
    # the mounted volume — not a CWD-relative dir the container never exposes.
    root = Path(data_dir) if data_dir is not None else Path(settings.DATA_DIR) / "demo"
    gen = _DemoGen(root / "cache")
    cfg = Config(data_dir=str(root / "projects"))
    deps = Deps(
        script_fn=_demo_script,
        gen_image_fn=gen.gen_image,
        gen_video_fn=gen.gen_video,
        tier0_fn=_demo_tier0,
        tier_a_fn=run_tier_a,          # REAL deterministic CV on the synthetic clips
        tier_b_fn=_demo_tier_b,
        repair_fn=_demo_repair,
        assemble_fn=assemble,          # REAL ffmpeg
        ledger=LedgerWriter(root / "ledger.jsonl"),
        custom_rule_fn=_demo_custom_rules,
        patch_video_fn=gen.gen_patch,
        narrate_fn=gen.narrate,
    )
    return Runtime(store=Store(str(root / "projects")), deps=deps, cfg=cfg, governor=None)
