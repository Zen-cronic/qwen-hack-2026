"""Vocabulary coverage — every declared assertion type must be evaluated by some tier.
A type no tier evaluates returns no result, which pipeline.py cannot tell from a pass:
a declared-but-unevaluated BLOCKING type is a gate that always opens."""

from types import SimpleNamespace

import cv2
import numpy as np
import pytest

import server.tier_b as tb
import server.tier0 as t0
from server.specs import ASSERTION_META, Assertion, AssertionType, ShotSpec, Tier
from server.tier_a import Clip, run_tier_a
from server.tier0 import Tier0Verifier
from server.tier_b import TierBVerifier

# One valid param set per type, so each can be instantiated and routed.
PARAMS: dict[AssertionType, dict] = {
    AssertionType.DURATION_BETWEEN: {"min_s": 1.0, "max_s": 9.0},
    AssertionType.BRIGHTNESS_RANGE: {"min": 0.0, "max": 255.0},
    AssertionType.FLICKER_BELOW: {"max_std": 100.0},
    AssertionType.SCENE_CUTS: {"max": 5},
    AssertionType.CAMERA_MOTION: {"direction": "any"},
    AssertionType.PALETTE_DELTAE: {"palette": ["#0b5fff"], "max_delta": 100.0},
    AssertionType.SUBJECT_PRESENT: {"subject": "knight"},
    AssertionType.IDENTITY_CONSISTENT: {"subject": "knight"},
    AssertionType.ACTION_COMPLETED: {"action": "the knight draws a sword"},
    AssertionType.TITLE_CARD_PRESENT: {},
}


def test_params_cover_the_vocabulary():
    """Guards the guard: a new type with no PARAMS entry must not silently skip below."""
    assert set(PARAMS) == set(AssertionType)


class _Completions:
    def create(self, **kwargs):
        msg = SimpleNamespace(content='{"verdict":"pass","reason":"ok"}')
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)],
                               usage=SimpleNamespace(prompt_tokens=10, completion_tokens=2))


class _Client:
    def __init__(self):
        self.chat = SimpleNamespace(completions=_Completions())


def _clip(n=3):
    frames = [np.full((32, 32, 3), 100, np.uint8) for _ in range(n)]
    gray = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in frames]
    return Clip(frames, gray, 8.0, 3.0, 32, 32)


def _still(tmp_path):
    p = tmp_path / "still.png"
    cv2.imwrite(str(p), np.full((32, 32, 3), 100, np.uint8))
    return str(p)


@pytest.mark.parametrize("atype", list(AssertionType), ids=lambda t: t.value)
def test_every_declared_type_is_evaluated_by_its_tier(atype, monkeypatch, tmp_path):
    spec = ShotSpec(index=0, prompt="a knight walks", subject="knight",
                    assertions=[Assertion(type=atype, params=PARAMS[atype])])
    tier = ASSERTION_META[atype].tier

    if tier is Tier.TIER_A:
        monkeypatch.setattr("server.tier_a.extract_clip", lambda p: _clip())
        results = run_tier_a("x.mp4", spec, str(tmp_path / "ev"))
    elif tier is Tier.TIER_B:
        monkeypatch.setattr(tb, "extract_clip", lambda p: _clip())
        results = TierBVerifier(_Client())("x.mp4", spec)
    elif tier is Tier.TIER0:
        monkeypatch.setattr(t0, "still_to_data_uri", lambda p: "data:image/png;base64,x")
        results = Tier0Verifier(_Client())(spec, _still(tmp_path))
    else:
        pytest.fail(f"{atype.value} has tier {tier} — no evaluator is wired for that tier")

    assert [r for r in results if r.type is atype], (
        f"{atype.value} is in the closed vocabulary but its tier ({tier.value}) returned no "
        f"result for it — a declared check that never runs. If it is blocking, the gate "
        f"silently opens; see this module's docstring."
    )


def _tier0_spec():
    return ShotSpec(index=0, prompt="a knight walks", subject="knight",
                    assertions=[Assertion(type=AssertionType.SUBJECT_PRESENT,
                                          params={"subject": "knight"})])


@pytest.mark.parametrize("mode", ["real", "fixtures", "demo"])
def test_every_production_path_wires_a_real_tier0(mode, monkeypatch, tmp_path):
    """The evaluator existing is not the same as the pipeline wiring it — assert the verdict."""
    import server.app as app_mod
    from server.config import settings as cfg_settings
    from server.demo import build_demo_runtime
    from server.fixtures import build_fixture_runtime
    from server.tier0 import Tier0Verifier

    # No network is reachable from this test: the only outbound call Tier-0 makes is _ask.
    monkeypatch.setattr(Tier0Verifier, "_ask", lambda self, q, uri: ("pass", "knight visible"))
    monkeypatch.setattr(app_mod, "DATA_ROOT", tmp_path / "root")
    # A wiring test needs no credential: the real/fixtures runtimes construct an OpenAI
    # client, whose ctor raises on an empty key (e.g. in CI, where no .env exists).
    monkeypatch.setattr(cfg_settings, "QWEN_API_KEY", "sk-test-wiring-only")

    if mode == "real":
        rt = app_mod.build_runtime()
    elif mode == "fixtures":
        rt = build_fixture_runtime(data_dir=str(tmp_path / "fx"))
    else:
        rt = build_demo_runtime(data_dir=str(tmp_path / "demo"))

    results = rt.deps.tier0_fn(_tier0_spec(), _still(tmp_path))
    assert [r for r in results if r.type is AssertionType.SUBJECT_PRESENT], (
        f"the {mode} runtime injects a tier0_fn that evaluates nothing — the still is "
        f"generated and billed, and subject_present (blocking) never gets a verdict"
    )
