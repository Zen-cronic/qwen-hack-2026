"""Repair agent (fake LLM) + ffmpeg assembly (real, tiny synthetic clips)."""

import shutil
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from server.assemble import AssembleError, assemble
from server.repair import RepairAgent
from server.specs import AssertionResult, AssertionType, ShotSpec, Status, Tier


class _Completions:
    def __init__(self, content, usage):
        self.content = content
        self.usage = usage

    def create(self, **kwargs):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))],
                               usage=self.usage)


class _Client:
    def __init__(self, content, usage):
        self.chat = SimpleNamespace(completions=_Completions(content, usage))


def _usage():
    return SimpleNamespace(prompt_tokens=200, completion_tokens=50)


def _camera_failure():
    return [AssertionResult(type=AssertionType.CAMERA_MOTION, tier=Tier.TIER_A, advisory=False,
                            status=Status.FAIL, detail="camera right (want left)",
                            measured={"detected": "right"})]


def test_repair_returns_revised_prompt_and_usage():
    client = _Client('{"prompt":"a fox runs left, locked static camera, no pan"}', _usage())
    new, usage = RepairAgent(client)(ShotSpec(index=0, prompt="a fox runs left"), _camera_failure())
    assert "static" in new
    assert usage.prompt_tokens == 200


def test_repair_falls_back_to_original_on_empty():
    client = _Client('{"prompt":""}', _usage())
    new, _ = RepairAgent(client)(ShotSpec(index=0, prompt="original prompt"), _camera_failure())
    assert new == "original prompt"


def _write_clip(path, bgr, n=10, fps=10, size=(160, 120)) -> bool:
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
    if not vw.isOpened():
        return False
    frame = np.zeros((size[1], size[0], 3), np.uint8)
    frame[:] = bgr
    for _ in range(n):
        vw.write(frame)
    vw.release()
    return True


def test_assemble_concats_two_clips(tmp_path):
    if shutil.which("ffmpeg") is None:
        pytest.skip("no ffmpeg")
    c1, c2 = tmp_path / "c1.mp4", tmp_path / "c2.mp4"
    if not _write_clip(c1, (0, 0, 255)) or not _write_clip(c2, (255, 0, 0)):
        pytest.skip("no mp4 writer backend")

    out = assemble([str(c1), str(c2)], str(tmp_path / "ep.mp4"))
    assert Path(out).exists() and Path(out).stat().st_size > 0
    cap = cv2.VideoCapture(out)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    assert total >= 15  # ~20 frames concatenated (allow encoder GOP variance)


def test_assemble_empty_raises():
    with pytest.raises(AssembleError):
        assemble([], "out.mp4")
