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
