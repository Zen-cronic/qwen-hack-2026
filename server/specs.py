"""The shot contract — Dailies' closed assertion vocabulary and validated types.

This is the "CI for generated video" thesis in one module. A shot spec is a prompt
plus a list of *assertions*: machine-checkable claims about the rendered clip. The
vocabulary is CLOSED — exactly 9 assertion types across three cost tiers. The
compiler (and the LLM output parser) run everything through `parse_assertions`,
which rejects any invented type or malformed params. That closure is what lets
downstream tiers assume every assertion is executable.

Tiers, cheapest first:
  tier0  — checked on a single t2i still BEFORE any video spend (1/25th cost)
  tier_a — deterministic CV on the rendered clip, ZERO tokens (the never-cut spine)
  tier_b — qwen-vl semantic verdicts (advisory; gated on the hour-zero smoke test)
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class Tier(str, Enum):
    TIER0 = "tier0"
    TIER_A = "tier_a"
    TIER_B = "tier_b"


class AssertionType(str, Enum):
    # tier_a — deterministic CV, zero tokens
    DURATION_BETWEEN = "duration_between"
    BRIGHTNESS_RANGE = "brightness_range"
    FLICKER_BELOW = "flicker_below"
    SCENE_CUTS = "scene_cuts"
    CAMERA_MOTION = "camera_motion"
    PALETTE_DELTAE = "palette_deltae"
    # tier0 — checked on the pre-render still (also observable in tier_b)
    SUBJECT_PRESENT = "subject_present"
    # tier_b — semantic, advisory (never blocks promotion)
    IDENTITY_CONSISTENT = "identity_consistent"
    ACTION_COMPLETED = "action_completed"


class Status(str, Enum):
    PENDING = "pending"
    PASS = "pass"
    FAIL = "fail"
    INCONCLUSIVE = "inconclusive"  # tier_b NO-GO, or evidence too weak to decide


class _Meta:
    """Static per-type schema: tier, whether advisory, and required param keys."""

    __slots__ = ("tier", "advisory", "required")

    def __init__(self, tier: Tier, advisory: bool, required: tuple[str, ...]):
        self.tier = tier
        self.advisory = advisory
        self.required = required


# The single source of truth for the closed vocabulary. parse_assertions enforces it.
ASSERTION_META: dict[AssertionType, _Meta] = {
    AssertionType.DURATION_BETWEEN: _Meta(Tier.TIER_A, False, ("min_s", "max_s")),
    AssertionType.BRIGHTNESS_RANGE: _Meta(Tier.TIER_A, False, ("min", "max")),
    AssertionType.FLICKER_BELOW: _Meta(Tier.TIER_A, False, ("max_std",)),
    AssertionType.SCENE_CUTS: _Meta(Tier.TIER_A, False, ("max",)),
    AssertionType.CAMERA_MOTION: _Meta(Tier.TIER_A, False, ("direction",)),
    AssertionType.PALETTE_DELTAE: _Meta(Tier.TIER_A, False, ("palette", "max_delta")),
    AssertionType.SUBJECT_PRESENT: _Meta(Tier.TIER0, False, ("subject",)),
    AssertionType.IDENTITY_CONSISTENT: _Meta(Tier.TIER_B, True, ("subject",)),
    AssertionType.ACTION_COMPLETED: _Meta(Tier.TIER_B, True, ("action",)),
}

CAMERA_DIRECTIONS = {"left", "right", "up", "down", "static", "any"}

# Assertion counts should stay in sync with PLAN.md's "exactly 9 assertion types".
assert len(ASSERTION_META) == 9, "closed vocabulary must be exactly 9 types"


class Assertion(BaseModel):
    """One machine-checkable claim about a rendered shot.

    Unknown `type` values fail at the enum boundary; missing/extra params fail in
    the model validator — together these give the "compiler rejects invented ones"
    guarantee the whole pipeline relies on.
    """

    model_config = {"frozen": True}

    type: AssertionType
    params: dict[str, Any] = Field(default_factory=dict)

    @property
    def tier(self) -> Tier:
        return ASSERTION_META[self.type].tier

    @property
    def advisory(self) -> bool:
        return ASSERTION_META[self.type].advisory

    @model_validator(mode="after")
    def _check_params(self) -> "Assertion":
        meta = ASSERTION_META[self.type]
        missing = [k for k in meta.required if k not in self.params]
        if missing:
            raise ValueError(f"{self.type.value} missing required params: {missing}")
        extra = [k for k in self.params if k not in meta.required]
        if extra:
            raise ValueError(f"{self.type.value} has unknown params: {extra}")
        if self.type is AssertionType.CAMERA_MOTION:
            direction = self.params["direction"]
            if direction not in CAMERA_DIRECTIONS:
                raise ValueError(f"camera_motion.direction must be one of {sorted(CAMERA_DIRECTIONS)}")
        return self


class AssertionResult(BaseModel):
    """The outcome of running one Assertion against one take."""

    type: AssertionType
    tier: Tier
    advisory: bool
    status: Status = Status.PENDING
    detail: str = ""
    measured: dict[str, Any] = Field(default_factory=dict)
    evidence: list[str] = Field(default_factory=list)  # relative media paths (frames)

    @classmethod
    def for_assertion(cls, a: Assertion, status: Status, detail: str = "", **kw: Any) -> "AssertionResult":
        return cls(type=a.type, tier=a.tier, advisory=a.advisory, status=status, detail=detail, **kw)


class ShotSpec(BaseModel):
    """A single shot: what to generate and what must be true of the result."""

    index: int
    prompt: str
    negative_prompt: str | None = None
    duration_s: int = 5  # fixed for wan2.1/2.2
    subject: str | None = None  # optional identity anchor for tier_b
    assertions: list[Assertion] = Field(default_factory=list)

    @field_validator("prompt")
    @classmethod
    def _prompt_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("shot prompt must contain words")
        return v


def parse_assertions(raw: list[dict[str, Any]]) -> list[Assertion]:
    """Validate a list of raw assertion dicts (from a YAML pack or an LLM) into
    Assertions. Raises ValueError on the first invalid entry — the enforcement
    point for the closed vocabulary."""
    out: list[Assertion] = []
    for i, item in enumerate(raw):
        try:
            out.append(Assertion.model_validate(item))
        except Exception as exc:  # noqa: BLE001 — re-raise with position context
            raise ValueError(f"assertion[{i}] invalid: {exc}") from exc
    return out
