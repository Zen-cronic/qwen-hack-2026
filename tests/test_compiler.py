"""Compiler: pack loading, override-merge, and closed-vocabulary rejection."""

import pytest

from server.compiler import (
    available_packs,
    compile_shots,
    load_pack,
    merge_assertions,
)
from server.specs import Assertion, AssertionType, Tier


def test_load_short_drama_pack():
    pack = load_pack("short_drama")
    assert pack.name == "short_drama"
    assert len(pack.defaults) == 4
    assert all(a.tier is Tier.TIER_A for a in pack.defaults)


def test_available_packs_lists_short_drama():
    assert "short_drama" in available_packs()


def test_load_missing_pack_raises():
    with pytest.raises(FileNotFoundError):
        load_pack("does_not_exist")


def test_merge_overrides_same_type_and_appends_new():
    defaults = [
        Assertion(type=AssertionType.DURATION_BETWEEN, params={"min_s": 4.0, "max_s": 6.0}),
        Assertion(type=AssertionType.SCENE_CUTS, params={"max": 1}),
    ]
    dynamic = [
        Assertion(type=AssertionType.DURATION_BETWEEN, params={"min_s": 2.0, "max_s": 3.0}),
        Assertion(type=AssertionType.CAMERA_MOTION, params={"direction": "left"}),
    ]
    merged = merge_assertions(defaults, dynamic)
    types = [a.type for a in merged]
    assert types.count(AssertionType.DURATION_BETWEEN) == 1  # overridden, not duplicated
    dur = next(a for a in merged if a.type is AssertionType.DURATION_BETWEEN)
    assert dur.params["min_s"] == 2.0  # the dynamic one won
    assert AssertionType.SCENE_CUTS in types and AssertionType.CAMERA_MOTION in types
    assert len(merged) == 3


def test_compile_shots_merges_defaults_with_dynamic():
    pack = load_pack("short_drama")
    raw = [{
        "prompt": "a fox runs left across fresh snow",
        "subject": "fox",
        "assertions": [
            {"type": "camera_motion", "params": {"direction": "left"}},
            {"type": "subject_present", "params": {"subject": "fox"}},
        ],
    }]
    specs = compile_shots(raw, pack)
    assert len(specs) == 1
    s = specs[0]
    assert s.index == 0 and s.subject == "fox"
    assert len(s.assertions) == 6  # 4 pack defaults + 2 dynamic (no type overlap)


def test_compile_rejects_invented_assertion_with_shot_index():
    pack = load_pack("short_drama")
    raw = [{"prompt": "x", "assertions": [{"type": "make_it_pretty", "params": {}}]}]
    with pytest.raises(ValueError) as ei:
        compile_shots(raw, pack)
    assert "shot[0]" in str(ei.value)


def test_compile_missing_prompt_raises():
    with pytest.raises(ValueError):
        compile_shots([{"assertions": []}], load_pack("short_drama"))


def test_extra_defaults_apply_to_every_shot():
    pack = load_pack("short_drama")
    extra = [Assertion(type=AssertionType.TITLE_CARD_PRESENT, params={})]
    raw = [
        {"prompt": "a"},
        {"prompt": "b", "assertions": [{"type": "camera_motion", "params": {"direction": "left"}}]},
    ]
    specs = compile_shots(raw, pack, extra_defaults=extra)
    assert all(any(a.type is AssertionType.TITLE_CARD_PRESENT for a in s.assertions) for s in specs)


def test_shot_assertion_overrides_extra_default_of_same_type():
    pack = load_pack("short_drama")
    extra = [Assertion(type=AssertionType.CAMERA_MOTION, params={"direction": "right"})]
    raw = [{"prompt": "a", "assertions": [{"type": "camera_motion", "params": {"direction": "left"}}]}]
    specs = compile_shots(raw, pack, extra_defaults=extra)
    cams = [a for a in specs[0].assertions if a.type is AssertionType.CAMERA_MOTION]
    assert len(cams) == 1 and cams[0].params["direction"] == "left"  # shot-specific wins


def test_compile_shots_carries_narration_through():
    # Regression: compile_shots built specs by hand and dropped narration, so every shot
    # fell back to a slate.
    pack = load_pack("short_drama")
    specs = compile_shots(
        [{"prompt": "a lighthouse at dusk", "narration": "For thirty years he watched."}], pack
    )
    assert specs[0].narration == "For thirty years he watched."


def test_compile_shots_without_narration_leaves_it_unset():
    pack = load_pack("short_drama")
    assert compile_shots([{"prompt": "a lighthouse at dusk"}], pack)[0].narration is None


def test_compile_shots_carries_speaker_through():
    pack = load_pack("short_drama")
    specs = compile_shots(
        [{"prompt": "a lighthouse at dusk", "narration": "I have turned this light.",
          "speaker": "the keeper"}], pack
    )
    assert specs[0].speaker == "the keeper"
