"""The demo runtime end to end — the one that must produce a sounded cut on camera."""

import json
import shutil
import subprocess
import threading
import time

import pytest

from server.demo import build_demo_runtime
from server.metrics import ResourceKind
from server.pipeline import Pipeline
from server.store import ProjectState, ProjectStatus


def _streams(path: str) -> list[dict]:
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        pytest.skip("no ffprobe")
    out = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "stream=codec_type,codec_name,duration",
         "-of", "json", path], capture_output=True, text=True)
    return json.loads(out.stdout or "{}").get("streams", [])


def _run_demo(tmp_path, max_shots=3, timeout=90.0):
    rt = build_demo_runtime(data_dir=str(tmp_path))
    rt.store.create(ProjectState(id="d1", premise="a corgi at the market",
                                 pack="short_drama", max_shots=max_shots))
    pipe = Pipeline(rt.store, "d1", rt.deps, rt.cfg)
    thread = threading.Thread(target=pipe.run)
    thread.start()

    end = time.monotonic() + timeout
    while time.monotonic() < end and rt.store.get("d1").status is not ProjectStatus.AWAITING_REVIEW:
        time.sleep(0.02)
    rt.store.signal_review("d1")
    thread.join(timeout=timeout)
    assert not thread.is_alive(), "demo pipeline did not finish"
    return rt, rt.store.get("d1")


def test_demo_episode_carries_narration(tmp_path):
    """Two assertions, because either alone is a false pass: silent mux, or an unused row."""
    rt, p = _run_demo(tmp_path)
    assert p.status is ProjectStatus.DONE and p.episode_path

    kinds = [s["codec_type"] for s in _streams(p.episode_path)]
    assert "audio" in kinds, f"the demo episode shipped silent — streams: {kinds}"

    rows = [json.loads(line) for line in (tmp_path / "ledger.jsonl").read_text().splitlines()]
    audio = [r for r in rows if r.get("kind") == ResourceKind.AUDIO.value]
    shipped = [s for s in p.shots if s.certified]
    assert len(audio) == len(shipped), "not every shipped shot was narrated"
    assert not [r for r in audio if "FAILED" in (r.get("note") or "")]


def test_demo_episode_audio_spans_the_whole_cut(tmp_path):
    """A track that stops after shot 0 is the failure `-shortest` causes without `apad`,
    and it looks fine in a stream listing — so compare the two durations, not just presence."""
    _, p = _run_demo(tmp_path)
    by_type = {s["codec_type"]: s for s in _streams(p.episode_path)}
    video, audio = float(by_type["video"]["duration"]), float(by_type["audio"]["duration"])
    assert abs(video - audio) < 0.5, f"audio {audio}s does not span the {video}s cut"
