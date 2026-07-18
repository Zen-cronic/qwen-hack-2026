"""Tier-A — deterministic CV checks on the rendered clip. Zero tokens. Never cut.

This is the spine of "CI for generated video": six checks that need no model, so
they run on every take for free and carry the kill-shot demo even if Tier-B is
down. Each check returns (Status, measured, detail); run_tier_a extracts frames
once and dispatches the Tier-A assertions of a shot.

Camera-motion convention: dense optical flow measures how CONTENT moves; the camera
moves opposite. Content drifting right => camera panned left. The synthetic-shift
unit test pins this sign so a regression can't silently invert it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from server.specs import AssertionResult, AssertionType, ShotSpec, Status, Tier

TARGET_FPS = 8
FRAME_WIDTH = 320
SCENE_CUT_CORR = 0.6       # HSV hist correlation below this between adjacent frames = a cut
STATIC_FLOW_THRESH = 0.4   # px/frame; camera flow magnitude below this reads as "static"


@dataclass
class Clip:
    frames_bgr: list[np.ndarray]
    frames_gray: list[np.ndarray]
    fps: float
    duration_s: float
    width: int
    height: int

    @property
    def n(self) -> int:
        return len(self.frames_gray)


def extract_clip(path: str, target_fps: int = TARGET_FPS, width: int = FRAME_WIDTH) -> Clip:
    cap = cv2.VideoCapture(str(path))
    src_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration = total / src_fps if src_fps > 0 and total > 0 else 0.0
    step = max(1, round(src_fps / target_fps)) if src_fps > 0 else 1

    bgr: list[np.ndarray] = []
    gray: list[np.ndarray] = []
    decoded = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if decoded % step == 0:
            h, w = frame.shape[:2]
            small = cv2.resize(frame, (width, max(1, round(h * width / max(1, w)))))
            bgr.append(small)
            gray.append(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY))
        decoded += 1
    cap.release()

    if duration <= 0 and decoded > 0 and src_fps > 0:
        duration = decoded / src_fps
    height = bgr[0].shape[0] if bgr else 0
    return Clip(bgr, gray, src_fps, duration, width, height)


def _luma_per_frame(clip: Clip) -> list[float]:
    return [float(g.mean()) for g in clip.frames_gray]


def check_duration(clip: Clip, p: dict):
    # An unreadable clip measures 0.00s, which would FAIL the bounds — reporting a
    # harness error as a contract violation. INCONCLUSIVE, never a fabricated verdict.
    if clip.n == 0:
        return Status.INCONCLUSIVE, {}, "no decodable frames — unreadable clip, not a short one"
    if clip.duration_s <= 0:
        return Status.INCONCLUSIVE, {}, "container reports no duration/fps — cannot measure"
    d = clip.duration_s
    ok = p["min_s"] <= d <= p["max_s"]
    return (Status.PASS if ok else Status.FAIL, {"duration_s": round(d, 3)},
            f"{d:.2f}s vs [{p['min_s']}, {p['max_s']}]")


def check_brightness(clip: Clip, p: dict):
    if clip.n == 0:
        return Status.INCONCLUSIVE, {}, "no frames"
    m = float(np.mean(_luma_per_frame(clip)))
    ok = p["min"] <= m <= p["max"]
    return (Status.PASS if ok else Status.FAIL, {"mean_brightness": round(m, 1)},
            f"mean luma {m:.1f} vs [{p['min']}, {p['max']}]")


def check_flicker(clip: Clip, p: dict):
    if clip.n < 2:
        return Status.INCONCLUSIVE, {}, "need >= 2 frames"
    s = float(np.std(_luma_per_frame(clip)))
    ok = s <= p["max_std"]
    return (Status.PASS if ok else Status.FAIL, {"flicker_std": round(s, 2)},
            f"luma std {s:.2f} vs <= {p['max_std']}")


def _hsv_hist(bgr: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [50, 60], [0, 180, 0, 256])
    cv2.normalize(hist, hist)
    return hist


def check_scene_cuts(clip: Clip, p: dict):
    if clip.n < 2:
        return Status.INCONCLUSIVE, {}, "need >= 2 frames"
    hists = [_hsv_hist(b) for b in clip.frames_bgr]
    cuts = sum(1 for a, b in zip(hists, hists[1:])
               if cv2.compareHist(a, b, cv2.HISTCMP_CORREL) < SCENE_CUT_CORR)
    ok = cuts <= p["max"]
    return (Status.PASS if ok else Status.FAIL, {"scene_cuts": cuts},
            f"{cuts} cut(s) vs <= {p['max']}")


def _mean_content_flow(clip: Clip) -> tuple[float, float]:
    dxs, dys = [], []
    for a, b in zip(clip.frames_gray, clip.frames_gray[1:]):
        flow = cv2.calcOpticalFlowFarneback(a, b, None, 0.5, 3, 15, 3, 5, 1.2, 0)
        dxs.append(float(flow[..., 0].mean()))
        dys.append(float(flow[..., 1].mean()))
    if not dxs:
        return 0.0, 0.0
    return float(np.mean(dxs)), float(np.mean(dys))


def detect_camera_direction(clip: Clip) -> tuple[str, float, float, float]:
    mdx, mdy = _mean_content_flow(clip)
    cdx, cdy = -mdx, -mdy  # camera moves opposite to content
    mag = math.hypot(cdx, cdy)
    if mag < STATIC_FLOW_THRESH:
        return "static", cdx, cdy, mag
    if abs(cdx) >= abs(cdy):
        return ("right" if cdx > 0 else "left"), cdx, cdy, mag
    return ("down" if cdy > 0 else "up"), cdx, cdy, mag  # image y grows downward


def check_camera_motion(clip: Clip, p: dict):
    if clip.n < 2:
        return Status.INCONCLUSIVE, {}, "need >= 2 frames"
    want = p["direction"]
    detected, cdx, cdy, mag = detect_camera_direction(clip)
    measured = {"detected": detected, "camera_dx": round(cdx, 3),
                "camera_dy": round(cdy, 3), "magnitude": round(mag, 3)}
    if want == "any":
        ok = detected != "static"
    elif want == "static":
        ok = detected == "static"
    else:
        ok = detected == want
    return (Status.PASS if ok else Status.FAIL, measured,
            f"camera {detected} (want {want}), |v|={mag:.2f}")


def _rgb_to_lab(rgb) -> np.ndarray:
    """True CIE L*a*b* — L* in [0,100], a*/b* in ~[-127,127], so Euclidean distance
    is ΔE*76. Must go through the float path: cv2's uint8 Lab scales L* by 255/100
    while only offsetting a*/b*, so distances there overweight lightness ~2.55x and
    are not ΔE of any kind (white comes back as [255,128,128] instead of [100,0,0])."""
    arr = np.float32(rgb).reshape(1, 1, 3) / 255.0
    return cv2.cvtColor(arr, cv2.COLOR_RGB2LAB)[0, 0].astype(float)


def _hex_to_lab(h: str) -> np.ndarray:
    h = h.lstrip("#")
    return _rgb_to_lab([int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)])


def _dominant_labs(clip: Clip, k: int) -> list[np.ndarray]:
    samples = []
    stride = max(1, clip.n // 8)
    for b in clip.frames_bgr[::stride]:
        rgb = cv2.cvtColor(b, cv2.COLOR_BGR2RGB).reshape(-1, 3)
        # deterministic even sampling — avoids flaky palettes across runs
        idx = np.linspace(0, len(rgb) - 1, min(500, len(rgb))).astype(int)
        samples.append(rgb[idx])
    data = np.vstack(samples).astype(np.float32)
    kk = max(1, min(k, len(data)))
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 10, 1.0)
    _, _, centers = cv2.kmeans(data, kk, None, crit, 3, cv2.KMEANS_PP_CENTERS)
    return [_rgb_to_lab(c) for c in centers]


def check_palette_deltae(clip: Clip, p: dict):
    if clip.n == 0:
        return Status.INCONCLUSIVE, {}, "no frames"
    ref = [_hex_to_lab(h) for h in p["palette"]]
    dom = _dominant_labs(clip, k=max(len(ref), 3))
    deltas = [min(float(np.linalg.norm(r - d)) for d in dom) for r in ref]
    mean_d = float(np.mean(deltas))
    ok = mean_d <= p["max_delta"]
    return (Status.PASS if ok else Status.FAIL, {"mean_deltae": round(mean_d, 2)},
            f"mean ΔE*76 {mean_d:.1f} vs <= {p['max_delta']}")


_CHECKS = {
    AssertionType.DURATION_BETWEEN: check_duration,
    AssertionType.BRIGHTNESS_RANGE: check_brightness,
    AssertionType.FLICKER_BELOW: check_flicker,
    AssertionType.SCENE_CUTS: check_scene_cuts,
    AssertionType.CAMERA_MOTION: check_camera_motion,
    AssertionType.PALETTE_DELTAE: check_palette_deltae,
}


def run_tier_a(video_path: str, spec: ShotSpec, evidence_dir: str) -> list[AssertionResult]:
    """Run every Tier-A assertion of `spec` against the clip. The injected TierAFn."""
    tier_a = [a for a in spec.assertions if a.tier is Tier.TIER_A]
    if not tier_a:
        return []
    clip = extract_clip(video_path)

    evidence: list[str] = []
    ev_dir = Path(evidence_dir)
    ev_dir.mkdir(parents=True, exist_ok=True)
    if clip.n:
        fp = ev_dir / "frame_mid.png"
        cv2.imwrite(str(fp), clip.frames_bgr[clip.n // 2])
        evidence = [str(fp)]

    results: list[AssertionResult] = []
    for a in tier_a:
        try:
            status, measured, detail = _CHECKS[a.type](clip, a.params)
        except Exception as exc:  # noqa: BLE001 — a bad frame shouldn't crash the run
            status, measured, detail = Status.INCONCLUSIVE, {}, f"check error: {exc}"
        results.append(AssertionResult.for_assertion(a, status, detail=detail,
                                                     measured=measured, evidence=evidence))
    return results
