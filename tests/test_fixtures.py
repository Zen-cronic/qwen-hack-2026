"""Real-video fixture pack. Offline — asserts the pinning that keeps the pack free."""

from server.fixtures import PAN_ASKED, PAN_REPAIRED, _fixture_repair, fixture_shots
from server.specs import ShotSpec
from server.wan import DRAFT_MODEL, cache_key

# The clips behind these keys cost real free-tier quota (~100s of generation each) and are
# what makes every later fixture run free. cache_key() is sha1 over the prompt, so editing
# a prompt -- even to fix a typo -- orphans the paid-for clip and silently re-bills. If
# this test fails you have changed a cache key: revert the wording, or re-warm on purpose
# with scripts/warm_fixtures.py and update the hash here.
PINNED_KEYS = {
    "PAN_ASKED": (PAN_ASKED, "8017c2f56bbb499ba4b416aace8c9c2e223c7034"),
    "PAN_REPAIRED": (PAN_REPAIRED, "8e193dace9b7f98c1920f8f24661e04f6792d65e"),
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
    """The pan is the claim under test. Asserting it on shots we have no reason to expect
    it on would manufacture failures rather than measure them."""
    shots = fixture_shots(3)
    with_cam = [i for i, s in enumerate(shots)
                if any(a["type"] == "camera_motion" for a in s["assertions"])]
    assert with_cam == [1]
    assert shots[1]["prompt"] == PAN_ASKED


def test_fixture_shots_are_deep_copies():
    """compile_shots merges pack defaults into these dicts; sharing them across runs would
    leak one run's mutations into the next."""
    first, second = fixture_shots(3), fixture_shots(3)
    first[0]["assertions"][0]["params"]["min_s"] = 99.0
    assert second[0]["assertions"][0]["params"]["min_s"] == 4.0


def test_max_shots_truncates():
    assert len(fixture_shots(1)) == 1
    assert len(fixture_shots(3)) == 3


def test_fixture_runtime_wires_real_narration(tmp_path):
    """Wan clips are silent, so the episode's sound is a real qwen-tts slate per shot. A
    refactor that drops narrate_fn would ship a silent demo — pin that it stays wired.
    Construction is offline (no model call until synthesize runs)."""
    from server.fixtures import build_fixture_runtime
    from server.tts import TTSClient

    rt = build_fixture_runtime(data_dir=str(tmp_path))
    assert rt.deps.narrate_fn is not None
    assert getattr(rt.deps.narrate_fn, "__self__", None).__class__ is TTSClient
