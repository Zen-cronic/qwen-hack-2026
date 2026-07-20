"""Tier-A — deterministic OpenCV checks on the rendered clip. Zero tokens.

Camera-motion sign convention: optical flow measures CONTENT motion; the camera moves
opposite. A unit test pins this sign — do not invert it.
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
    step: int = 1  # source frames per sampled frame — the sampled-index -> seconds bridge

    @property
    def n(self) -> int:
        return len(self.frames_gray)

    def t(self, i: int) -> float:
        """Seconds into the clip for sampled frame `i` (frames are decimated by `step`)."""
        return i * self.step / self.fps if self.fps > 0 else i / float(TARGET_FPS)

    def window(self, lo: int, hi: int) -> list[float]:
        """The [start, end] second-window spanned by sampled frames lo..hi."""
        return [round(self.t(lo), 2), round(self.t(hi), 2)]


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
    return Clip(bgr, gray, src_fps, duration, width, height, step)


def _luma_per_frame(clip: Clip) -> list[float]:
    return [float(g.mean()) for g in clip.frames_gray]


def _longest_run(bad: list[bool]) -> tuple[int, int] | None:
    """Longest contiguous True run in `bad`, as inclusive (start, end) indices."""
    best: tuple[int, int] | None = None
    cur: tuple[int, int] | None = None
    for i, b in enumerate(bad):
        if not b:
            cur = None
            continue
        cur = (cur[0], i) if cur else (i, i)
        if best is None or (cur[1] - cur[0]) > (best[1] - best[0]):
            best = cur
    return best


def _band_excess(v: float, lo: float, hi: float) -> float:
    """How far `v` falls outside [lo, hi]; 0.0 when inside."""
    return max(lo - v, v - hi, 0.0)


def check_duration(clip: Clip, p: dict):
    # An unreadable clip is INCONCLUSIVE, never FAIL — 0.00s is a harness error, not a violation.
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
    lum = _luma_per_frame(clip)
    m = float(np.mean(lum))
    ok = p["min"] <= m <= p["max"]
    measured = {"mean_brightness": round(m, 1)}
    if not ok:
        # The clip mean broke the contract; name the stretch that dragged it out of band.
        run = _longest_run([_band_excess(v, p["min"], p["max"]) > 0 for v in lum])
        if run:
            lo, hi = run
            measured["fail_window_s"] = clip.window(lo, hi)
            excess = [_band_excess(v, p["min"], p["max"]) for v in lum[lo:hi + 1]]
            measured["worst_frame"] = lo + int(np.argmax(excess))
    return (Status.PASS if ok else Status.FAIL, measured,
            f"mean luma {m:.1f} vs [{p['min']}, {p['max']}]")


def check_flicker(clip: Clip, p: dict):
    if clip.n < 2:
        return Status.INCONCLUSIVE, {}, "need >= 2 frames"
    lum = _luma_per_frame(clip)
    s = float(np.std(lum))
    ok = s <= p["max_std"]
    measured = {"flicker_std": round(s, 2)}
    if not ok:
        # Flicker is an ADJACENT-frame property, so the locus is the biggest luma jump.
        jumps = np.abs(np.diff(lum))
        i = int(np.argmax(jumps))
        measured["fail_window_s"] = clip.window(i, i + 1)
        measured["worst_frame"] = i + 1
        measured["max_jump"] = round(float(jumps[i]), 1)
    return (Status.PASS if ok else Status.FAIL, measured,
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
    # Keep the frame each cut lands on, so a failure can say when and not only how many.
    cut_frames = [i + 1 for i, (a, b) in enumerate(zip(hists, hists[1:]))
                  if cv2.compareHist(a, b, cv2.HISTCMP_CORREL) < SCENE_CUT_CORR]
    cuts = len(cut_frames)
    ok = cuts <= p["max"]
    measured = {"scene_cuts": cuts}
    if not ok:
        measured["cut_times_s"] = [round(clip.t(i), 2) for i in cut_frames]
        # The first cut over budget is the one to repair; earlier ones are within contract.
        first_over = cut_frames[min(p["max"], cuts - 1)]
        measured["fail_window_s"] = clip.window(first_over - 1, first_over)
        measured["worst_frame"] = first_over
    return (Status.PASS if ok else Status.FAIL, measured,
            f"{cuts} cut(s) vs <= {p['max']}")


def _content_flow_series(clip: Clip) -> tuple[list[float], list[float]]:
    """Per-adjacent-pair mean content flow; pair `i` spans sampled frames i..i+1."""
    dxs, dys = [], []
    for a, b in zip(clip.frames_gray, clip.frames_gray[1:]):
        flow = cv2.calcOpticalFlowFarneback(a, b, None, 0.5, 3, 15, 3, 5, 1.2, 0)
        dxs.append(float(flow[..., 0].mean()))
        dys.append(float(flow[..., 1].mean()))
    return dxs, dys


def _mean_content_flow(clip: Clip) -> tuple[float, float]:
    dxs, dys = _content_flow_series(clip)
    if not dxs:
        return 0.0, 0.0
    return float(np.mean(dxs)), float(np.mean(dys))


def _classify(cdx: float, cdy: float) -> tuple[str, float]:
    """Camera vector -> (direction, magnitude). Content moves opposite to the camera."""
    mag = math.hypot(cdx, cdy)
    if mag < STATIC_FLOW_THRESH:
        return "static", mag
    if abs(cdx) >= abs(cdy):
        return ("right" if cdx > 0 else "left"), mag
    return ("down" if cdy > 0 else "up"), mag  # image y grows downward


def detect_camera_direction(clip: Clip) -> tuple[str, float, float, float]:
    mdx, mdy = _mean_content_flow(clip)
    cdx, cdy = -mdx, -mdy  # camera moves opposite to content
    detected, mag = _classify(cdx, cdy)
    return detected, cdx, cdy, mag


def _motion_satisfies(detected: str, want: str) -> bool:
    if want == "any":
        return detected != "static"
    if want == "static":
        return detected == "static"
    return detected == want


def check_camera_motion(clip: Clip, p: dict):
    if clip.n < 2:
        return Status.INCONCLUSIVE, {}, "need >= 2 frames"
    want = p["direction"]
    dxs, dys = _content_flow_series(clip)          # one Farneback pass, reused below
    cdx, cdy = -float(np.mean(dxs)), -float(np.mean(dys))
    detected, mag = _classify(cdx, cdy)
    measured = {"detected": detected, "camera_dx": round(cdx, 3),
                "camera_dy": round(cdy, 3), "magnitude": round(mag, 3)}
    ok = _motion_satisfies(detected, want)
    if not ok:
        # Re-run the same verdict per frame-pair and take the longest offending stretch.
        per = [_classify(-x, -y)[0] for x, y in zip(dxs, dys)]
        run = _longest_run([not _motion_satisfies(d, want) for d in per])
        if run:
            lo, hi = run
            measured["fail_window_s"] = clip.window(lo, hi + 1)
            measured["worst_frame"] = (lo + hi) // 2 + 1
            measured["fail_span_frames"] = hi - lo + 1
    return (Status.PASS if ok else Status.FAIL, measured,
            f"camera {detected} (want {want}), |v|={mag:.2f}")


def _rgb_to_lab(rgb) -> np.ndarray:
    """True CIE L*a*b*, so Euclidean distance is ΔE*76. Must use the float path — cv2's
    uint8 Lab rescales L* and its distances are not ΔE of any kind."""
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

        # A failure's own frame leads its evidence; the mid-frame stays as context.
        ev = evidence
        wf = measured.get("worst_frame")
        if status is Status.FAIL and isinstance(wf, int) and 0 <= wf < clip.n:
            fp = ev_dir / f"{a.type.value}_f{wf}.png"
            cv2.imwrite(str(fp), clip.frames_bgr[wf])
            measured["worst_frame_s"] = round(clip.t(wf), 2)
            ev = [str(fp), *evidence]

        results.append(AssertionResult.for_assertion(a, status, detail=detail,
                                                     measured=measured, evidence=ev))
    return results
