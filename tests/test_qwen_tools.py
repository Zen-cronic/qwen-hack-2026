"""Qwen custom-tool wrappers around run_shot_tests — delegation and schema, no LLM."""

import json

import pytest

from server.demo import _write_clip
from server.qwen_tools import RUN_SHOT_TESTS_TOOL, run_shot_tests_json


def test_run_shot_tests_json_accepts_dict_and_str(tmp_path):
    clip = tmp_path / "clip.mp4"
    _write_clip(clip, "right")
    args = {"video_path": str(clip),
            "assertions": [{"type": "camera_motion", "params": {"direction": "right"}}]}
    from_dict = json.loads(run_shot_tests_json(args))
    from_str = json.loads(run_shot_tests_json(json.dumps(args)))
    assert from_dict == from_str
    assert from_dict["passed"] is True
    assert from_dict["summary"]["total"] == 1


def test_run_shot_tests_json_rejects_invented_assertion(tmp_path):
    clip = tmp_path / "clip.mp4"
    _write_clip(clip, "static")
    with pytest.raises(ValueError):  # closed-vocab gate flows through the tool
        run_shot_tests_json({"video_path": str(clip), "assertions": [{"type": "nope", "params": {}}]})


def test_function_calling_schema_is_well_formed():
    assert RUN_SHOT_TESTS_TOOL["type"] == "function"
    fn = RUN_SHOT_TESTS_TOOL["function"]
    assert fn["name"] == "run_shot_tests"
    params = fn["parameters"]
    assert params["type"] == "object"
    assert "video_path" in params["properties"]
    assert params["required"] == ["video_path"]


def test_qwen_agent_custom_tool_registers_and_calls(tmp_path):
    pytest.importorskip("qwen_agent")  # optional [agent] extra
    from server.qwen_tools import register_qwen_agent_tool

    cls = register_qwen_agent_tool()
    assert cls.name == "run_shot_tests"
    assert cls.description and isinstance(cls.parameters, list)

    clip = tmp_path / "clip.mp4"
    _write_clip(clip, "static")
    out = json.loads(cls().call(json.dumps({"video_path": str(clip),
                                            "assertions": [{"type": "duration_between",
                                                            "params": {"min_s": 1, "max_s": 10}}]})))
    assert out["passed"] is True and out["summary"]["total"] == 1
