"""Closed-vocabulary enforcement — the core 'CI for video' guarantee."""

import pytest
from pydantic import ValidationError

from server.specs import (
    ASSERTION_META,
    Assertion,
    AssertionType,
    ShotSpec,
    Tier,
    parse_assertions,
)


def test_vocabulary_is_exactly_ten():
    assert len(ASSERTION_META) == 10
    assert set(ASSERTION_META) == set(AssertionType)


def test_title_card_present_is_paramless_advisory():
    a = Assertion(type=AssertionType.TITLE_CARD_PRESENT, params={})
    assert a.tier is Tier.TIER_B
    assert a.advisory is True
    with pytest.raises(ValidationError):  # closed vocab: no params accepted
        Assertion(type=AssertionType.TITLE_CARD_PRESENT, params={"text": "hi"})


def test_valid_tier_a_assertion_reports_tier_and_not_advisory():
    a = Assertion(type=AssertionType.CAMERA_MOTION, params={"direction": "left"})
    assert a.tier is Tier.TIER_A
    assert a.advisory is False


def test_tier_b_assertions_are_advisory():
    a = Assertion(type=AssertionType.ACTION_COMPLETED, params={"action": "the door opens"})
    assert a.tier is Tier.TIER_B
    assert a.advisory is True


def test_unknown_assertion_type_rejected():
    with pytest.raises(ValidationError):
        Assertion(type="teleport_effect", params={})


def test_missing_required_param_rejected():
    with pytest.raises(ValidationError):
        Assertion(type=AssertionType.DURATION_BETWEEN, params={"min_s": 4.0})  # missing max_s


def test_unknown_param_rejected():
    with pytest.raises(ValidationError):
        Assertion(type=AssertionType.SCENE_CUTS, params={"max": 1, "bogus": 2})


def test_bad_camera_direction_rejected():
    with pytest.raises(ValidationError):
        Assertion(type=AssertionType.CAMERA_MOTION, params={"direction": "sideways"})


def test_parse_assertions_reports_offending_index():
    raw = [
        {"type": "scene_cuts", "params": {"max": 1}},
        {"type": "not_a_real_check", "params": {}},
    ]
    with pytest.raises(ValueError) as ei:
        parse_assertions(raw)
    assert "assertion[1]" in str(ei.value)


def test_shotspec_rejects_empty_prompt():
    with pytest.raises(ValidationError):
        ShotSpec(index=0, prompt="   ")


def test_result_carries_the_assertion_params():
    # The UI names a check in plain language ("The ginger street cat is in frame"),
    # which is impossible from the type alone — the subject, the bounds, and the cut
    # allowance all live in params. So a result has to carry them.
    from server.specs import AssertionResult, Status

    a = Assertion(type=AssertionType.SUBJECT_PRESENT, params={"subject": "ginger_street_cat"})
    r = AssertionResult.for_assertion(a, Status.PASS, detail="seen")
    assert r.params == {"subject": "ginger_street_cat"}

    # A copy, not a reference: mutating a result must not rewrite the spec it came from.
    r.params["subject"] = "someone else"
    assert a.params["subject"] == "ginger_street_cat"

    # scene_cuts max=0 and max=1 are different promises; both must survive onto the result.
    zero = AssertionResult.for_assertion(
        Assertion(type=AssertionType.SCENE_CUTS, params={"max": 0}), Status.PASS)
    assert zero.params["max"] == 0
