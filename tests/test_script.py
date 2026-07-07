"""Script agent with a fake OpenAI-shaped client — zero quota."""

import json
from types import SimpleNamespace

import pytest

from server.compiler import compile_shots, load_pack
from server.script import _vocabulary_doc, compile_custom_rules, script_and_specs
from server.specs import parse_assertions


class _FakeCompletions:
    def __init__(self, content: str, usage):
        self._content = content
        self._usage = usage
        self.last_kwargs: dict | None = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        message = SimpleNamespace(content=self._content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=self._usage)


class _FakeClient:
    def __init__(self, content: str, usage):
        self.chat = SimpleNamespace(completions=_FakeCompletions(content, usage))


def _usage(pin=120, pout=60):
    return SimpleNamespace(prompt_tokens=pin, completion_tokens=pout, total_tokens=pin + pout)


def test_vocabulary_doc_covers_all_types():
    doc = _vocabulary_doc()
    for t in ("duration_between", "camera_motion", "subject_present",
              "identity_consistent", "action_completed", "palette_deltae"):
        assert t in doc


def test_script_parses_json_caps_shots_and_returns_usage():
    content = json.dumps({"shots": [
        {"prompt": "a fox runs left", "subject": "fox",
         "assertions": [{"type": "camera_motion", "params": {"direction": "left"}}]},
        {"prompt": "the fox stops and looks back", "assertions": []},
        {"prompt": "a third shot beyond the cap", "assertions": []},
    ]})
    client = _FakeClient(content, _usage())
    raw, usage = script_and_specs("a fox in snow", pack=load_pack("short_drama"),
                                  max_shots=2, client=client, model="qwen-plus")
    assert len(raw) == 2  # capped at max_shots
    assert usage.prompt_tokens == 120
    # end-to-end: the agent's output compiles cleanly against the closed vocabulary
    specs = compile_shots(raw, load_pack("short_drama"))
    assert len(specs) == 2
    assert any(a.type.value == "camera_motion" for a in specs[0].assertions)


def test_script_tolerates_code_fenced_json():
    content = "```json\n" + json.dumps({"shots": [{"prompt": "x", "assertions": []}]}) + "\n```"
    client = _FakeClient(content, _usage())
    raw, _ = script_and_specs("p", pack=load_pack("short_drama"), max_shots=5,
                              client=client, model="qwen-plus")
    assert len(raw) == 1 and raw[0]["prompt"] == "x"


def test_compile_custom_rules_maps_plain_language_to_closed_vocab():
    content = json.dumps({"assertions": [
        {"type": "title_card_present", "params": {}},
        {"type": "camera_motion", "params": {"direction": "right"}},
    ]})
    client = _FakeClient(content, _usage())
    raw, usage = compile_custom_rules(
        ["a title card must be visible", "the camera should pan right"],
        client=client, model="qwen-plus")
    assertions = parse_assertions(raw)  # raw dicts validate against the closed vocabulary
    assert {a.type.value for a in assertions} == {"title_card_present", "camera_motion"}
    assert usage.prompt_tokens == 120


def test_compile_custom_rules_output_still_gated_by_closed_vocab():
    content = json.dumps({"assertions": [{"type": "make_it_epic", "params": {}}]})
    client = _FakeClient(content, _usage())
    raw, _ = compile_custom_rules(["make it epic"], client=client, model="qwen-plus")
    with pytest.raises(ValueError):  # an invented type is rejected before any video spend
        parse_assertions(raw)
