"""The short_drama pack is data — it must validate against the closed vocabulary."""

from pathlib import Path

import yaml

from server.specs import Tier, parse_assertions

PACK = Path(__file__).resolve().parents[1] / "packs" / "short_drama.yaml"


def test_short_drama_defaults_are_valid_zero_token_assertions():
    data = yaml.safe_load(PACK.read_text(encoding="utf-8"))
    assertions = parse_assertions(data["defaults"])
    assert len(assertions) == 4
    # Pack defaults must all be Tier-A (the never-cut, zero-token spine).
    assert all(a.tier is Tier.TIER_A for a in assertions)
