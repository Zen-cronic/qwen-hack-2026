"""Agent pipeline planner — topology, validation, and the deterministic demo stub."""

import pytest
from pydantic import ValidationError

from server.agent_plan import (
    PipelinePlan,
    expand_plan,
    plan_from_message,
)
from server.config import settings

PACKS = ["brand_rules", "short_drama"]


def _ids(plan: PipelinePlan) -> list[str]:
    return [n.id for n in plan.nodes]


def test_expand_plan_topology():
    plan = expand_plan("a lonely lighthouse keeper", "short_drama", 3, [])
    # Canonical spine + a gen/check pair per shot.
    assert _ids(plan) == [
        "script", "stills", "review",
        "gen-0", "check-0", "gen-1", "check-1", "gen-2", "check-2",
        "assemble", "episode",
    ]
    kinds = {n.id: n.kind for n in plan.nodes}
    assert kinds["script"] == "stage" and kinds["assemble"] == "stage"
    assert kinds["review"] == "review" and kinds["episode"] == "episode"
    assert kinds["gen-0"] == "shot" and kinds["check-0"] == "check"
    # 2 spine edges + 3 per shot + 1 tail.
    assert len(plan.edges) == 2 + 3 * 3 + 1
    pairs = {(e.source, e.target) for e in plan.edges}
    assert ("script", "stills") in pairs and ("stills", "review") in pairs
    for i in range(3):
        assert ("review", f"gen-{i}") in pairs
        assert (f"gen-{i}", f"check-{i}") in pairs
        assert (f"check-{i}", "assemble") in pairs
    assert ("assemble", "episode") in pairs


def test_expand_plan_clamps_shots():
    assert expand_plan("p", "short_drama", 99, []).max_shots == 12
    assert expand_plan("p", "short_drama", 0, []).max_shots == 1
    assert len([n for n in expand_plan("p", "short_drama", 5, []).nodes if n.kind == "shot"]) == 5


def test_expand_plan_drops_blank_checks():
    plan = expand_plan("p", "short_drama", 2, ["  ", "a title card must be visible", ""])
    assert plan.custom_checks == ["a title card must be visible"]


def test_pipelineplan_rejects_out_of_range_shots():
    with pytest.raises(ValidationError):
        PipelinePlan(premise="x", pack="short_drama", max_shots=13, nodes=[], edges=[])
    with pytest.raises(ValidationError):
        PipelinePlan(premise="x", pack="short_drama", max_shots=0, nodes=[], edges=[])


def test_pipelineplan_rejects_empty_premise():
    with pytest.raises(ValidationError):
        PipelinePlan(premise="", pack="short_drama", max_shots=3, nodes=[], edges=[])


def test_plan_from_message_demo_is_deterministic():
    msg = "a 4-shot noir chase that must end on a title card"
    a, ta = plan_from_message(msg, demo=True, packs=PACKS)
    b, tb = plan_from_message(msg, demo=True, packs=PACKS)
    assert a.model_dump() == b.model_dump()
    assert a.max_shots == 4
    assert "a title card must be visible" in a.custom_checks
    # The premise carries the user's brief verbatim.
    assert a.premise == msg
    # The transcript is the tool-call evidence.
    assert ta == tb
    assert ta[0]["name"] == "build_pipeline_graph"
    assert ta[0]["result"]["max_shots"] == 4


def test_plan_stub_defaults_shot_count_and_pack():
    plan, _ = plan_from_message("a street cat assembles a heist crew", demo=True, packs=PACKS)
    assert plan.max_shots == 3           # no explicit count -> 3
    assert plan.pack == "short_drama"    # narrative default


def test_plan_stub_picks_brand_pack_on_cue():
    plan, _ = plan_from_message("a 2-shot promo enforcing our brand logo safety", demo=True, packs=PACKS)
    assert plan.pack == "brand_rules"
    assert plan.max_shots == 2


def test_plan_from_message_falls_back_without_key(monkeypatch):
    # demo=False but no key -> the deterministic stub, never a live call.
    monkeypatch.setattr(settings, "QWEN_API_KEY", "")
    plan, transcript = plan_from_message("a 5-shot documentary", demo=False, packs=PACKS)
    assert plan.max_shots == 5
    assert transcript[0]["name"] == "build_pipeline_graph"


def test_plan_pack_falls_back_to_available():
    # An unknown pack from the model is snapped to a real one.
    plan, _ = plan_from_message("something", demo=True, packs=["brand_rules"])
    assert plan.pack == "brand_rules"
