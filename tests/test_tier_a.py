"""Tier-A deterministic CV checks on synthetic frames + one real mp4."""

from pathlib import Path

import cv2
import numpy as np
import pytest

from server.specs import AssertionType, ShotSpec, Status, parse_assertions
from server.tier_a import (
    Clip,
    _hex_to_lab,
    check_brightness,
    check_camera_motion,
    check_duration,
    check_flicker,
    check_palette_deltae,
    check_scene_cuts,
    detect_camera_direction,
    extract_clip,
    run_tier_a,
)


def _gray_clip(frames_gray, fps=8.0, duration=5.0):
    bgr = [cv2.cvtColor(g, cv2.COLOR_GRAY2BGR) for g in frames_gray]
    h, w = frames_gray[0].shape
    return Clip(bgr, list(frames_gray), fps, duration, w, h)


def _solid_gray(value, w=64, h=48):
    return np.full((h, w), value, np.uint8)


def _solid_bgr_clip(bgr, n=5, w=64, h=48):
    frame = np.zeros((h, w, 3), np.uint8)
    frame[:] = bgr
    frames = [frame.copy() for _ in range(n)]
    gray = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in frames]
    return Clip(frames, gray, 8.0, 5.0, w, h)


def test_duration():
    clip = _gray_clip([_solid_gray(128)] * 4, duration=5.0)
    assert check_duration(clip, {"min_s": 4.0, "max_s": 6.0})[0] is Status.PASS
    assert check_duration(clip, {"min_s": 5.5, "max_s": 6.0})[0] is Status.FAIL


def test_duration_unreadable_clip_is_inconclusive_not_fail(tmp_path):
    # Regression: a missing/corrupt clip measured 0.00s and FAILed the duration
    # contract — a harness error fabricated as a rejection.
    empty = Clip([], [], 0.0, 0.0, 320, 0)
    assert check_duration(empty, {"min_s": 4.0, "max_s": 6.0})[0] is Status.INCONCLUSIVE

    bogus = tmp_path / "not_a_video.mp4"
    bogus.write_bytes(b"this is not an mp4")
    clip = extract_clip(str(bogus))
    assert check_duration(clip, {"min_s": 4.0, "max_s": 6.0})[0] is Status.INCONCLUSIVE

    # Frames decoded but the container lies about fps/duration: still not a verdict.
    no_meta = _gray_clip([_solid_gray(128)] * 3, fps=0.0, duration=0.0)
    assert check_duration(no_meta, {"min_s": 4.0, "max_s": 6.0})[0] is Status.INCONCLUSIVE


def test_brightness():
    clip = _gray_clip([_solid_gray(220)] * 3)
    assert check_brightness(clip, {"min": 25, "max": 235})[0] is Status.PASS
    assert check_brightness(clip, {"min": 25, "max": 100})[0] is Status.FAIL


def test_flicker():
    steady = _gray_clip([_solid_gray(128)] * 5)
    assert check_flicker(steady, {"max_std": 10.0})[0] is Status.PASS
    flick = _gray_clip([_solid_gray(30), _solid_gray(220), _solid_gray(30), _solid_gray(220)])
    assert check_flicker(flick, {"max_std": 10.0})[0] is Status.FAIL


def test_scene_cuts():
    same = _solid_bgr_clip((100, 100, 100), n=5)
    assert check_scene_cuts(same, {"max": 1})[0] is Status.PASS
    red = np.zeros((48, 64, 3), np.uint8); red[:] = (0, 0, 255)
    blue = np.zeros((48, 64, 3), np.uint8); blue[:] = (255, 0, 0)
    frames = [red, blue, red, blue]
    gray = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in frames]
    alt = Clip(frames, gray, 8.0, 5.0, 64, 48)
    assert check_scene_cuts(alt, {"max": 0})[0] is Status.FAIL


def test_camera_motion_synthetic_shift():
    # Two offset crops of one wide texture: content moves RIGHT, so the camera panned LEFT.
    # Blurred noise, not a ramp — Farneback needs trackable curvature.
    h, w, shift = 64, 120, 8
    rng = np.random.default_rng(0)
    wide = (rng.random((h, w + shift)) * 255).astype(np.uint8)
    wide = cv2.GaussianBlur(wide, (0, 0), 2.0)
    f1 = np.ascontiguousarray(wide[:, shift : shift + w])
    f2 = np.ascontiguousarray(wide[:, :w])
    clip = _gray_clip([f1, f2])

    detected, cdx, cdy, mag = detect_camera_direction(clip)
    assert mag > 0.4, f"flow too weak to classify: {mag}"
    assert detected == "left"
    assert check_camera_motion(clip, {"direction": "left"})[0] is Status.PASS
    assert check_camera_motion(clip, {"direction": "right"})[0] is Status.FAIL


def test_palette_deltae():
    red = np.zeros((48, 64, 3), np.uint8); red[:] = (0, 0, 255)  # BGR red
    gray = [cv2.cvtColor(red, cv2.COLOR_BGR2GRAY)] * 4
    clip = Clip([red] * 4, gray, 8.0, 5.0, 64, 48)
    assert check_palette_deltae(clip, {"palette": ["#ff0000"], "max_delta": 30.0})[0] is Status.PASS
    assert check_palette_deltae(clip, {"palette": ["#00ff00"], "max_delta": 30.0})[0] is Status.FAIL


def test_lab_conversion_is_true_cie_scale():
    # White is L*=100, a*=b*=0 in real CIE Lab; the old uint8 path overweighted lightness.
    white = _hex_to_lab("#ffffff")
    assert abs(white[0] - 100.0) < 1.0 and abs(white[1]) < 1.0 and abs(white[2]) < 1.0
    # sRGB red, published CIE value (D65): (53.24, 80.09, 67.20).
    red = _hex_to_lab("#ff0000")
    assert abs(red[0] - 53.24) < 2.0
    assert abs(red[1] - 80.09) < 3.0
    assert abs(red[2] - 67.20) < 3.0


def test_palette_deltae_lightness_no_longer_dominates():
    # Regression for the 2.55x lightness overweight: a pure-lightness pair, true ΔE*76 ≈ 10.4.
    g = np.full((48, 64, 3), 128, np.uint8)
    clip = Clip([g] * 4, [cv2.cvtColor(g, cv2.COLOR_BGR2GRAY)] * 4, 8.0, 5.0, 64, 48)
    status, measured, _ = check_palette_deltae(clip, {"palette": ["#9b9b9b"], "max_delta": 15.0})
    assert status is Status.PASS
    assert 8.0 < measured["mean_deltae"] < 13.0  # pins the metric, not just the verdict


def _blurred_noise(h, w, seed=1):
    rng = np.random.default_rng(seed)
    return cv2.GaussianBlur((rng.random((h, w)) * 255).astype(np.uint8), (0, 0), 2.0)


def test_clip_time_mapping_accounts_for_decimation():
    # A sampled index is not a source index: frames are decimated by `step`, so a
    # locus reported in seconds must divide by the SOURCE fps after multiplying back.
    clip = Clip([], [_solid_gray(128)] * 12, 30.0, 4.0, 64, 48, 4)
    assert clip.t(0) == 0.0
    assert abs(clip.t(9) - 9 * 4 / 30.0) < 1e-9
    assert clip.window(3, 6) == [round(3 * 4 / 30.0, 2), round(6 * 4 / 30.0, 2)]

    # No fps reported: the decimated grid is the only clock, and t() must still be sane.
    blind = Clip([], [_solid_gray(128)] * 8, 0.0, 0.0, 64, 48, 1)
    assert abs(blind.t(8) - 1.0) < 1e-9  # 8 frames at TARGET_FPS=8


def test_passing_check_reports_no_locus():
    # A locus is a claim about where something broke. A passing check must not make one.
    steady = _gray_clip([_solid_gray(128)] * 6)
    status, measured, _ = check_flicker(steady, {"max_std": 10.0})
    assert status is Status.PASS
    assert "fail_window_s" not in measured and "worst_frame" not in measured


def test_flicker_locus_names_the_flash_frame():
    # Steady 128 except one blown frame at index 4: the defect is the JUMP into it,
    # not the frame furthest from the clip mean.
    lum = [128, 128, 128, 128, 250, 128, 128, 128]
    clip = _gray_clip([_solid_gray(v) for v in lum], fps=8.0)
    status, measured, _ = check_flicker(clip, {"max_std": 5.0})
    assert status is Status.FAIL
    assert measured["worst_frame"] == 4
    assert measured["max_jump"] == pytest.approx(122.0, abs=1.0)
    assert measured["fail_window_s"] == [round(3 / 8, 2), round(4 / 8, 2)]


def test_brightness_locus_spans_the_out_of_band_run():
    # Dark for the first 5 frames, in-band after: the mean fails, and the locus must
    # point at the dark stretch rather than the whole clip.
    lum = [10, 10, 10, 10, 10, 140, 140, 140]
    clip = _gray_clip([_solid_gray(v) for v in lum], fps=8.0)
    status, measured, _ = check_brightness(clip, {"min": 100, "max": 200})
    assert status is Status.FAIL
    assert measured["fail_window_s"] == [0.0, round(4 / 8, 2)]
    assert 0 <= measured["worst_frame"] <= 4


def test_scene_cuts_locus_reports_every_cut_and_the_first_over_budget():
    red = np.zeros((48, 64, 3), np.uint8); red[:] = (0, 0, 255)
    blue = np.zeros((48, 64, 3), np.uint8); blue[:] = (255, 0, 0)
    frames = [red, red, blue, blue, red]  # cuts land on frames 2 and 4
    gray = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in frames]
    clip = Clip(frames, gray, 8.0, 5.0, 64, 48)

    status, measured, _ = check_scene_cuts(clip, {"max": 0})
    assert status is Status.FAIL
    assert measured["scene_cuts"] == 2
    assert measured["cut_times_s"] == [round(2 / 8, 2), round(4 / 8, 2)]
    assert measured["worst_frame"] == 2  # zero allowed -> the FIRST cut is the violation

    # One cut is within contract, so the second is the one that breaks it.
    status, measured, _ = check_scene_cuts(clip, {"max": 1})
    assert status is Status.FAIL
    assert measured["worst_frame"] == 4


def test_camera_motion_locus_finds_the_half_that_misbehaves():
    # Pan one way, then reverse: the averages cancel, so the locus must be the reversed
    # half. Direction is read off the clip so the test can't invert with the flow sign.
    h, w, shift, half = 64, 120, 8, 8
    wide = _blurred_noise(h, w + shift * half)
    fwd = [np.ascontiguousarray(wide[:, i * shift: i * shift + w]) for i in range(half)]
    frames = fwd + fwd[::-1]
    clip = _gray_clip(frames, fps=8.0)

    want, _, _, _ = detect_camera_direction(_gray_clip(fwd[:2]))
    assert want != "static", "fixture must actually pan"

    status, measured, _ = check_camera_motion(clip, {"direction": want})
    assert status is Status.FAIL
    lo, hi = measured["fail_window_s"]
    assert hi > lo
    assert lo >= 0.8, f"offending stretch should be the second half, got {lo}-{hi}s"
    assert measured["fail_span_frames"] >= 5


def test_failing_check_writes_its_own_evidence_frame(tmp_path):
    # Regression for "evidence is the midpoint regardless of what failed": a failing
    # check must lead with the frame it actually indicted.
    path = tmp_path / "dark.mp4"
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (128, 96))
    if not vw.isOpened():
        pytest.skip("no mp4 writer backend in this opencv build")
    for _ in range(20):
        vw.write(np.full((96, 128, 3), 30, np.uint8))
    vw.release()

    spec = ShotSpec(index=0, prompt="x", assertions=parse_assertions([
        {"type": "brightness_range", "params": {"min": 100, "max": 235}},
    ]))
    ev_dir = tmp_path / "ev"
    results = run_tier_a(str(path), spec, str(ev_dir))
    if not results or results[0].status is Status.INCONCLUSIVE:
        pytest.skip("opencv could not decode the written mp4 on this platform")

    r = results[0]
    assert r.status is Status.FAIL
    assert "worst_frame_s" in r.measured
    assert r.evidence[0].endswith(f"brightness_range_f{r.measured['worst_frame']}.png")
    assert Path(r.evidence[0]).exists()
    assert (ev_dir / "frame_mid.png").exists()  # context frame is still written


def test_run_tier_a_end_to_end_on_real_mp4(tmp_path):
    path = tmp_path / "clip.mp4"
    fps, n = 10, 20  # 2.0s
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (128, 96))
    if not vw.isOpened():
        pytest.skip("no mp4 writer backend in this opencv build")
    for _ in range(n):
        vw.write(np.full((96, 128, 3), 120, np.uint8))
    vw.release()

    spec = ShotSpec(index=0, prompt="x", assertions=parse_assertions([
        {"type": "duration_between", "params": {"min_s": 1.0, "max_s": 3.0}},
        {"type": "brightness_range", "params": {"min": 25, "max": 235}},
    ]))
    results = run_tier_a(str(path), spec, str(tmp_path / "ev"))
    if not results or all(r.status is Status.INCONCLUSIVE for r in results):
        pytest.skip("opencv could not decode the written mp4 on this platform")

    by = {r.type: r for r in results}
    assert by[AssertionType.DURATION_BETWEEN].status is Status.PASS
    assert by[AssertionType.BRIGHTNESS_RANGE].status is Status.PASS
    assert (tmp_path / "ev" / "frame_mid.png").exists()
