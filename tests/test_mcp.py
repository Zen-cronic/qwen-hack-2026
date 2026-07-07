"""MCP run_shot_tests — the productization surface, tested on synthetic clips.

Exercises the core conformance function directly (no `mcp` package required); the
protocol wrapper is a thin lazy layer over this.
"""

import pytest

from server.demo import _write_clip
from server.mcp_server import run_shot_tests


def test_run_shot_tests_reports_conformance(tmp_path):
    clip = tmp_path / "clip.mp4"
    _write_clip(clip, "right")  # synthetic clip whose camera pans right
    report = run_shot_tests(str(clip), assertions=[
        {"type": "duration_between", "params": {"min_s": 1, "max_s": 10}},
        {"type": "camera_motion", "params": {"direction": "right"}},
    ])
    assert report["passed"] is True
    assert report["summary"]["total"] == 2
    assert {c["type"] for c in report["checks"]} == {"duration_between", "camera_motion"}


def test_run_shot_tests_gates_on_non_advisory_failure(tmp_path):
    clip = tmp_path / "clip.mp4"
    _write_clip(clip, "static")  # no motion
    report = run_shot_tests(str(clip), assertions=[
        {"type": "camera_motion", "params": {"direction": "right"}},  # will fail — clip is static
    ])
    assert report["passed"] is False
    assert report["summary"]["failed"] == 1


def test_run_shot_tests_rejects_invented_assertion(tmp_path):
    clip = tmp_path / "clip.mp4"
    _write_clip(clip, "static")
    with pytest.raises(ValueError):  # closed-vocab gate, before any check runs
        run_shot_tests(str(clip), assertions=[{"type": "make_it_pretty", "params": {}}])


def test_run_shot_tests_notes_skipped_vlm_checks(tmp_path):
    clip = tmp_path / "clip.mp4"
    _write_clip(clip, "static")
    report = run_shot_tests(str(clip), assertions=[
        {"type": "title_card_present", "params": {}},  # Tier-B: can't run without the VLM pipeline
    ])
    assert report["skipped_vlm_checks"] == ["title_card_present"]
    assert report["summary"]["total"] == 0  # nothing Tier-A to run
