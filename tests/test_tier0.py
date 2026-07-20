"""Tier-0 still screen — fake VL client, real image encoding, zero quota.
Live behaviour verified against qwen-vl-plus in docs/verification.md section 5."""

import base64
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from server.specs import Assertion, AssertionResult, AssertionType, ShotSpec, Status
from server.tier0 import STILL_WIDTH, Tier0Verifier, inconclusive_verifier, still_to_data_uri


class _Completions:
    def __init__(self, content, usage, raises=None):
        self.content = content
        self.usage = usage
        self.raises = raises
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        if self.raises:
            raise self.raises
        msg = SimpleNamespace(content=self.content)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=self.usage)


class _Client:
    def __init__(self, content='{"verdict":"pass","reason":"ok"}', usage=None, raises=None):
        self.completions = _Completions(content, usage or SimpleNamespace(prompt_tokens=325,
                                                                          completion_tokens=33), raises)
        self.chat = SimpleNamespace(completions=self.completions)


def _spec(subject="the keeper"):
    return ShotSpec(index=0, prompt="the keeper climbs", subject=subject,
                    assertions=[Assertion(type=AssertionType.SUBJECT_PRESENT,
                                          params={"subject": subject})])


def _write_still(path, w=1024, h=1024):
    cv2.imwrite(str(path), np.full((h, w, 3), 120, np.uint8))
    return str(path)


def _decode(uri):
    im = cv2.imdecode(np.frombuffer(base64.b64decode(uri.split(",", 1)[1]), np.uint8),
                      cv2.IMREAD_COLOR)
    return im.shape[1], im.shape[0]


def test_still_is_downscaled_before_it_is_sent(tmp_path):
    """VLM image tokens scale with pixels; a full-res 1024px still would make the cheap
    pre-screen cost more than the Tier-B batch it exists to avoid."""
    uri = still_to_data_uri(_write_still(tmp_path / "s.png", 1024, 1024))
    assert _decode(uri) == (STILL_WIDTH, STILL_WIDTH)


def test_small_still_is_not_upscaled(tmp_path):
    uri = still_to_data_uri(_write_still(tmp_path / "s.png", 200, 100))
    assert _decode(uri) == (200, 100)


def test_aspect_ratio_survives_the_downscale(tmp_path):
    w, h = _decode(still_to_data_uri(_write_still(tmp_path / "s.png", 1024, 576)))
    assert (w, h) == (STILL_WIDTH, 288)


@pytest.mark.parametrize("verdict,expected", [
    ("pass", Status.PASS), ("fail", Status.FAIL), ("inconclusive", Status.INCONCLUSIVE),
    ("banana", Status.INCONCLUSIVE),  # an unparseable verdict must not read as a pass
])
def test_verdict_mapping(verdict, expected, tmp_path):
    c = _Client(content='{"verdict":"%s","reason":"r"}' % verdict)
    results = Tier0Verifier(c)(_spec(), _write_still(tmp_path / "s.png"))
    assert [r.status for r in results] == [expected]


def test_blocking_and_evidence_carry_through(tmp_path):
    still = _write_still(tmp_path / "s.png")
    r = Tier0Verifier(_Client())(_spec(), still)[0]
    assert r.advisory is False          # subject_present is a real gate, not a warning
    assert r.evidence == [still]        # the still IS the evidence for a Tier-0 verdict


def test_usage_is_reported_then_reset(tmp_path):
    v = Tier0Verifier(_Client())
    v(_spec(), _write_still(tmp_path / "s.png"))
    assert v.pop_last_usage() == (325, 33)
    assert v.pop_last_usage() == (0, 0)


def test_missing_still_is_inconclusive_not_a_failure(tmp_path):
    """A t2i failure must not be reported as 'the subject is absent'. INCONCLUSIVE goes
    to the human at the review gate; FAIL would fabricate a rejection from missing data."""
    c = _Client()
    results = Tier0Verifier(c)(_spec(), str(tmp_path / "does-not-exist.png"))
    assert [r.status for r in results] == [Status.INCONCLUSIVE]
    assert c.completions.calls == 0     # no still, no spend


def test_vl_error_degrades_to_inconclusive(tmp_path):
    c = _Client(raises=RuntimeError("boom"))
    r = Tier0Verifier(c)(_spec(), _write_still(tmp_path / "s.png"))[0]
    assert r.status is Status.INCONCLUSIVE
    assert "boom" in r.detail


def test_no_tier0_assertions_means_no_call(tmp_path):
    c = _Client()
    spec = ShotSpec(index=0, prompt="p", assertions=[
        Assertion(type=AssertionType.CAMERA_MOTION, params={"direction": "left"})])
    assert Tier0Verifier(c)(spec, _write_still(tmp_path / "s.png")) == []
    assert c.completions.calls == 0


def test_inconclusive_verifier_returns_a_verdict_not_an_empty_list():
    """The NO-GO fallback's whole point: [] silently certifies, INCONCLUSIVE does not."""
    results = inconclusive_verifier(_spec(), "s.png")
    assert [r.status for r in results] == [Status.INCONCLUSIVE]
    assert all(isinstance(r, AssertionResult) for r in results)
