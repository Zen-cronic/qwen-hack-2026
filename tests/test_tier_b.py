"""Tier-B VLM verdicts — fake client, monkeypatched frame extraction, zero quota."""

from types import SimpleNamespace

import cv2
import numpy as np

import server.tier_b as tb
from server.pipeline import _pop_usage
from server.specs import ShotSpec, Status, parse_assertions
from server.tier_a import Clip
from server.tier_b import TierBVerifier, inconclusive_verifier


def _clip(n=3):
    frames = [np.full((32, 32, 3), 100, np.uint8) for _ in range(n)]
    gray = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in frames]
    return Clip(frames, gray, 8.0, 3.0, 32, 32)


class _VLCompletions:
    def __init__(self, content, usage):
        self.content = content
        self.usage = usage
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        msg = SimpleNamespace(content=self.content)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=self.usage)


class _VLClient:
    def __init__(self, content, usage):
        self.chat = SimpleNamespace(completions=_VLCompletions(content, usage))


def _usage(pin=300, pout=15):
    return SimpleNamespace(prompt_tokens=pin, completion_tokens=pout)


def _spec():
    return ShotSpec(index=0, prompt="a knight walks", subject="knight",
                    assertions=parse_assertions([
                        {"type": "identity_consistent", "params": {"subject": "knight"}},
                        {"type": "action_completed", "params": {"action": "the knight draws a sword"}},
                    ]))


def test_pass_verdict_and_usage_accumulation(monkeypatch):
    monkeypatch.setattr(tb, "extract_clip", lambda p: _clip())
    v = TierBVerifier(_VLClient('{"verdict":"pass","reason":"consistent"}', _usage()))
    results = v("x.mp4", _spec())
    assert len(results) == 2
    assert all(r.status is Status.PASS for r in results)
    assert all(r.advisory for r in results)  # Tier-B is always advisory
    assert v.pop_last_usage() == (600, 30)   # 2 calls x (300, 15)
    assert v.pop_last_usage() == (0, 0)      # reset after pop


def test_fail_verdict_stays_advisory(monkeypatch):
    monkeypatch.setattr(tb, "extract_clip", lambda p: _clip())
    v = TierBVerifier(_VLClient('{"verdict":"fail","reason":"identity drifts"}', _usage()))
    results = v("x.mp4", _spec())
    assert all(r.status is Status.FAIL for r in results)
    assert all(r.advisory for r in results)  # a Tier-B FAIL never blocks promotion


def test_garbage_response_is_inconclusive(monkeypatch):
    monkeypatch.setattr(tb, "extract_clip", lambda p: _clip())
    v = TierBVerifier(_VLClient("totally not json", _usage()))
    results = v("x.mp4", _spec())
    assert all(r.status is Status.INCONCLUSIVE for r in results)


def test_no_frames_skips_vl_call(monkeypatch):
    monkeypatch.setattr(tb, "extract_clip", lambda p: Clip([], [], 0.0, 0.0, 0, 0))
    v = TierBVerifier(_VLClient('{"verdict":"pass"}', _usage()))
    results = v("x.mp4", _spec())
    assert all(r.status is Status.INCONCLUSIVE for r in results)
    assert v.client.chat.completions.calls == 0  # no wasted VL call


def test_no_tier_b_assertions_returns_empty():
    v = TierBVerifier(_VLClient("{}", _usage()))
    assert v("x.mp4", ShotSpec(index=0, prompt="a plain shot")) == []


def test_inconclusive_fallback_verifier():
    results = inconclusive_verifier("x.mp4", _spec())
    assert len(results) == 2
    assert all(r.status is Status.INCONCLUSIVE and r.advisory for r in results)


def test_pipeline_pop_usage_reads_stage_usage():
    class Stub:
        def pop_last_usage(self):
            return (50, 20)

    assert _pop_usage(Stub()) == (50, 20)
    assert _pop_usage(lambda *a: None) == (0, 0)  # plain function -> nothing
