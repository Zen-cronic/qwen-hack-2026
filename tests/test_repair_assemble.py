"""Repair agent (fake LLM) + ffmpeg assembly (real, tiny synthetic clips)."""

import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from server.assemble import AssembleError, assemble, mux_narration
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


def _probe(path: str) -> dict:
    """ffprobe stream summary — the only way to prove an audio track really exists."""
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        pytest.skip("no ffprobe")
    out = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "stream=codec_type,duration",
         "-of", "json", path], capture_output=True, text=True)
    return json.loads(out.stdout or "{}")


def _tone(path: Path, seconds: float) -> bool:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        return False
    r = subprocess.run([ffmpeg, "-y", "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
                        str(path)], capture_output=True)
    return r.returncode == 0 and path.exists()


def test_assemble_with_narration_produces_an_audio_track(tmp_path):
    if shutil.which("ffmpeg") is None:
        pytest.skip("no ffmpeg")
    c1, c2 = tmp_path / "c1.mp4", tmp_path / "c2.mp4"
    if not _write_clip(c1, (0, 0, 255)) or not _write_clip(c2, (255, 0, 0)):
        pytest.skip("no mp4 writer backend")
    wav = tmp_path / "vo.wav"
    if not _tone(wav, 0.4):
        pytest.skip("no lavfi audio")

    # Second shot has no narration: mixing sounded and silent segments is the case that
    # breaks a naive concat graph, so it is the one worth pinning.
    out = assemble([str(c1), str(c2)], str(tmp_path / "ep.mp4"), audio_paths=[str(wav), None])

    types = [s["codec_type"] for s in _probe(out).get("streams", [])]
    assert "video" in types and "audio" in types, f"expected both streams, got {types}"


def test_narration_shorter_than_the_clip_does_not_shorten_it(tmp_path):
    # Regression guard for -shortest without apad: a 0.2s line over a 2s shot would cut
    # the VIDEO to 0.2s, silently breaking the shot's duration contract.
    if shutil.which("ffmpeg") is None:
        pytest.skip("no ffmpeg")
    clip = tmp_path / "c.mp4"
    if not _write_clip(clip, (0, 255, 0), n=20, fps=10):  # 2.0s
        pytest.skip("no mp4 writer backend")
    wav = tmp_path / "short.wav"
    if not _tone(wav, 0.2):
        pytest.skip("no lavfi audio")

    out = mux_narration(str(clip), str(wav), str(tmp_path / "muxed.mp4"))
    cap = cv2.VideoCapture(out)
    frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    assert frames >= 15, f"video was truncated to the narration length ({frames} frames)"
