"""Real-video fixture pack. Offline — asserts the pinning that keeps the pack free."""

from server.fixtures import PAN_ASKED, PAN_REPAIRED, _fixture_repair, fixture_shots
from server.specs import ShotSpec
from server.wan import DRAFT_MODEL, cache_key

# cache_key() is sha1 over the prompt: rewording one orphans its paid-for clip and re-bills.
# To change a prompt on purpose, re-warm via scripts/warm_fixtures.py and update the hash here.
PINNED_KEYS = {
    "PAN_ASKED": (PAN_ASKED, "218bba835f9809ce433a0c17bd91f54be4434692"),
    "PAN_REPAIRED": (PAN_REPAIRED, "d7cbcd91c704d90acab49b8eadcfa55aa461fe7b"),
}


def test_pinned_prompts_keep_their_cache_keys():
    for name, (prompt, expected) in PINNED_KEYS.items():
        assert cache_key(DRAFT_MODEL, prompt, None, "1280*720", None) == expected, (
            f"{name} changed: its cached clip is now unreachable and this run will re-bill"
        )


def test_repair_rewrites_only_the_kill_shot():
    spec = ShotSpec(index=1, prompt=PAN_ASKED, assertions=[])
    prompt, usage = _fixture_repair(spec, [])
    assert prompt == PAN_REPAIRED
    assert usage.total_tokens == 0  # a pinned stage calls no model, so it bills nothing

    untouched = ShotSpec(index=0, prompt="a bottle among wet rocks", assertions=[])
    assert _fixture_repair(untouched, [])[0] == "a bottle among wet rocks"


def test_camera_motion_is_asserted_only_on_the_kill_shot():
    """Asserting the pan on shots we have no reason to expect it on manufactures failures."""
    shots = fixture_shots(3)
    with_cam = [i for i, s in enumerate(shots)
                if any(a["type"] == "camera_motion" for a in s["assertions"])]
    assert with_cam == [1]
    assert shots[1]["prompt"] == PAN_ASKED


def test_fixture_shots_are_deep_copies():
    """compile_shots merges into these dicts; sharing them leaks one run's mutations."""
    first, second = fixture_shots(3), fixture_shots(3)
    first[0]["assertions"][0]["params"]["min_s"] = 99.0
    assert second[0]["assertions"][0]["params"]["min_s"] == 4.0


def test_max_shots_truncates():
    assert len(fixture_shots(1)) == 1
    assert len(fixture_shots(3)) == 3


def test_fixture_runtime_wires_real_narration(tmp_path, monkeypatch):
    """Wan clips are silent, so dropping narrate_fn ships a silent demo — pin it stays wired."""
    from server.config import settings
    from server.fixtures import build_fixture_runtime
    from server.tts import TTSClient

    # Stand-in key: the fixtures runtime builds a WanClient eagerly and its ctor rejects "".
    monkeypatch.setattr(settings, "QWEN_API_KEY", "sk-test-wiring-only")
    rt = build_fixture_runtime(data_dir=str(tmp_path))
    assert rt.deps.narrate_fn is not None
    assert getattr(rt.deps.narrate_fn, "__self__", None).__class__ is TTSClient
