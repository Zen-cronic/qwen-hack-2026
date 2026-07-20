"""Targeted repair: anchor to the last good frame, regenerate, re-verify.

Uses the demo synthesizer for real mp4s and the REAL Tier-A, so the localization the
patch depends on is genuinely measured rather than hand-fed.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from server.demo import _write_clip
from server.metrics import LedgerWriter, ResourceKind
from server.patch import (
    anchor_second,
    extract_frame,
    localized_failure,
    patch_shot,
)
from server.pipeline import Config, Deps
from server.specs import (
    Assertion,
    AssertionResult,
    AssertionType,
    ShotSpec,
    Status,
    Tier,
    parse_assertions,
)
from server.store import ProjectState, ShotState, Store, Take, TakeStatus
from server.tier_a import run_tier_a

PAN_RIGHT = [{"type": "camera_motion", "params": {"direction": "right"}}]


def _result(atype, status, measured, advisory=False, tier=Tier.TIER_A):
    return AssertionResult(type=atype, tier=tier, advisory=advisory, status=status,
                           detail="", measured=measured)


def test_localized_failure_ignores_advisory_and_unlocated():
    # Advisory checks never block, so spending a generation to chase one would invert
    # the tier contract; an unlocated failure has no anchor to work from.
    advisory = _result(AssertionType.TITLE_CARD_PRESENT, Status.FAIL,
                       {"fail_window_s": [1.0, 2.0]}, advisory=True, tier=Tier.TIER_B)
    unlocated = _result(AssertionType.SCENE_CUTS, Status.FAIL, {"scene_cuts": 4})
    passing = _result(AssertionType.CAMERA_MOTION, Status.PASS, {"fail_window_s": [0.0, 1.0]})
    real = _result(AssertionType.CAMERA_MOTION, Status.FAIL, {"fail_window_s": [1.5, 3.0]})

    assert localized_failure([advisory, unlocated, passing]) is None
    assert localized_failure([advisory, unlocated, passing, real]) is real


def test_anchor_steps_back_from_the_window_and_clamps_at_zero():
    late = _result(AssertionType.CAMERA_MOTION, Status.FAIL, {"fail_window_s": [2.5, 4.0]})
    assert anchor_second(late) == pytest.approx(2.3)
    # A failure that starts at 0 has no earlier good frame — anchor at the first one.
    immediate = _result(AssertionType.CAMERA_MOTION, Status.FAIL, {"fail_window_s": [0.0, 5.0]})
    assert anchor_second(immediate) == 0.0


def test_extract_frame_is_full_resolution_and_survives_a_bad_seek(tmp_path):
    import cv2

    clip = tmp_path / "c.mp4"
    _write_clip(clip, "right")
    out = extract_frame(str(clip), 1.0, tmp_path / "a.png")
    assert out and Path(out).exists()
    img = cv2.imread(out)
    assert img.shape[1] == 320, "anchor must come from the source clip, not the 320px-wide analysis copy"

    # Seeking past the end falls back to frame 0 rather than returning nothing.
    assert extract_frame(str(clip), 999.0, tmp_path / "b.png") is not None
    assert extract_frame(str(tmp_path / "missing.mp4"), 0.0, tmp_path / "c.png") is None


def _project_with_failed_shot(tmp_path) -> tuple[Store, str]:
    """A one-shot project whose only take genuinely fails camera_motion, per real Tier-A."""
    clip = tmp_path / "draft.mp4"
    _write_clip(clip, "static")  # asserts a right pan, renders static — a real failure
    spec = ShotSpec(index=0, prompt="the keeper climbs, camera pans right",
                    assertions=parse_assertions(PAN_RIGHT))
    results = run_tier_a(str(clip), spec, str(tmp_path / "ev"))
    assert results and results[0].status is Status.FAIL
    assert "fail_window_s" in results[0].measured, "localization is the input this feature needs"

    take = Take(take_no=0, tier="draft", model="wan2.1-t2v-turbo", prompt=spec.prompt,
                status=TakeStatus.DONE, video_path=str(clip), results=results, passed=False)
    store = Store(str(tmp_path / "projects"))
    p = ProjectState(id="p1", premise="x", pack="short_drama", max_shots=1)
    p.shots = [ShotState(spec=spec, takes=[take])]
    store.create(p)
    return store, "p1"


def _deps(tmp_path, *, patch_direction: str, assembled: list):
    def gen_patch(prompt, model, frame_path):
        assert Path(frame_path).exists(), "the anchor frame must be written before generating"
        out = tmp_path / f"patched_{patch_direction}.mp4"
        _write_clip(out, patch_direction)
        return SimpleNamespace(status="SUCCEEDED", ok=True, local_path=str(out),
                               from_cache=False, seconds=5, cached_seconds=0, latency_ms=10)

    def gen_reroll(prompt, model, negative_prompt=None):
        # The whole-clip fallback: no anchor frame is passed, because there isn't one.
        out = tmp_path / f"reroll_{patch_direction}.mp4"
        _write_clip(out, patch_direction)
        return SimpleNamespace(status="SUCCEEDED", ok=True, local_path=str(out),
                               from_cache=False, seconds=5, cached_seconds=0, latency_ms=10)

    def fake_assemble(paths, out):
        assembled.append(list(paths))
        return out

    noop = lambda *a, **k: []
    return Deps(
        script_fn=lambda *a: ([], SimpleNamespace(prompt_tokens=0, completion_tokens=0)),
        gen_image_fn=lambda p: None,
        gen_video_fn=gen_reroll,
        tier0_fn=noop,
        tier_a_fn=run_tier_a,
        tier_b_fn=noop,
        repair_fn=lambda spec, failures: (
            f"{spec.prompt} [retake] enforce a steady camera that pans right",
            SimpleNamespace(prompt_tokens=90, completion_tokens=30)),
        assemble_fn=fake_assemble,
        ledger=LedgerWriter(),
        patch_video_fn=gen_patch,
    )


def test_patch_promotes_a_clip_that_now_passes(tmp_path):
    store, pid = _project_with_failed_shot(tmp_path)
    assembled: list = []
    deps = _deps(tmp_path, patch_direction="right", assembled=assembled)
    cfg = Config(data_dir=str(tmp_path / "projects"))

    out = patch_shot(store, pid, 0, deps, cfg, model="wan2.2-i2v-flash")

    assert out.ok, out.reason
    # This clip is static THROUGHOUT, so the failure window opens at t=0 and there is no
    # good frame to continue from. Anchoring there would pin the defect the patch exists
    # to remove (verification 3e), so the patch re-rolls and reports no anchor.
    assert out.anchor_s is None and out.anchor_frame is None
    st = store.get(pid).shots[0]
    assert st.certified and st.final_path == out.video_path
    assert [t.tier for t in st.takes] == ["draft", "patch"]
    assert st.takes[1].passed is True
    assert assembled == [[out.video_path]], "a passing patch re-concats the episode for free"

    # Billed to its own pool, never to the t2v draft/final counters the reserve rations.
    w = deps.ledger.wallet()
    assert w.patch_clips == 1 and w.draft_clips == 0 and w.final_clips == 0
    kinds = [e.kind for e in deps.ledger.entries()]
    assert ResourceKind.VIDEO_PATCH in kinds and ResourceKind.CHAT in kinds

    # The spend must also reach the PROJECT's ledger — that copy is what the wallet
    # meter renders, so recording only to the writer would leave a patch invisible.
    assert store.get(pid).wallet.patch_clips == 1
    assert [e.stage for e in store.get(pid).ledger] == ["patching", "patching"]


def test_a_patch_that_still_fails_does_not_replace_the_original(tmp_path):
    # The gate applies to repairs too: a patch has to earn the slot by re-verifying.
    store, pid = _project_with_failed_shot(tmp_path)
    assembled: list = []
    deps = _deps(tmp_path, patch_direction="static", assembled=assembled)  # still no pan
    cfg = Config(data_dir=str(tmp_path / "projects"))

    out = patch_shot(store, pid, 0, deps, cfg, model="wan2.2-i2v-flash")

    assert not out.ok and "still does not pass" in out.reason
    st = store.get(pid).shots[0]
    assert not st.certified and st.final_path is None
    assert len(st.takes) == 2, "the failed attempt is still recorded"
    assert assembled == [], "nothing to re-concat when the patch didn't earn the slot"


def test_patch_refuses_cleanly_when_there_is_nothing_to_anchor_to(tmp_path):
    store, pid = _project_with_failed_shot(tmp_path)
    cfg = Config(data_dir=str(tmp_path / "projects"))

    # No frame-anchored generator wired (e.g. the fixtures runtime).
    deps = _deps(tmp_path, patch_direction="right", assembled=[])
    deps.patch_video_fn = None
    assert not patch_shot(store, pid, 0, deps, cfg, model="wan2.2-i2v-flash").ok

    deps.patch_video_fn = lambda *a: None
    assert not patch_shot(store, pid, 9, deps, cfg, model="wan2.2-i2v-flash").ok

    # A clip that satisfies its contract has nothing to anchor to. Note the source is
    # re-measured, so emptying the stored results would NOT make this case — the clip
    # itself has to pass.
    good = tmp_path / "passing.mp4"
    _write_clip(good, "right")
    store.update(pid, lambda p: setattr(p.shots[0].takes[0], "video_path", str(good)))
    out = patch_shot(store, pid, 0, deps, cfg, model="wan2.2-i2v-flash")
    assert not out.ok and "Nothing to patch" in out.reason


def test_a_mid_clip_failure_anchors_instead_of_re_rolling(tmp_path):
    """The other half of the rule: when a good frame DOES precede the defect, preserve it.

    Anchoring is the whole point of a patch — it holds the composition Tier-0 approved and
    draws the separate i2v pool. The fully-static fixture can never reach this branch (its
    window opens at t=0), so the localization is injected to put the defect mid-clip.
    """
    store, pid = _project_with_failed_shot(tmp_path)
    assembled: list = []
    deps = _deps(tmp_path, patch_direction="right", assembled=assembled)
    seen: list[str] = []
    mid = _result(AssertionType.CAMERA_MOTION, Status.FAIL, {"fail_window_s": [1.5, 3.0]})
    good = _result(AssertionType.CAMERA_MOTION, Status.PASS, {})

    def tier_a(video_path, spec, evidence_dir):
        seen.append(video_path)
        return [mid] if len(seen) == 1 else [good]  # source fails mid-clip, patch passes

    deps.tier_a_fn = tier_a
    cfg = Config(data_dir=str(tmp_path / "projects"))

    out = patch_shot(store, pid, 0, deps, cfg, model="wan2.2-i2v-flash")

    assert out.ok, out.reason
    # 1.5 - ANCHOR_LEAD_S: the last frame BEFORE the defect, never the defect itself.
    assert out.anchor_s == 1.3 and Path(out.anchor_frame).exists()
    # The frame-anchored model ran, not the t2v re-roll.
    assert store.get(pid).shots[0].takes[1].model == "wan2.2-i2v-flash"
