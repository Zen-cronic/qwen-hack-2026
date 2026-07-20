"""Real-video fixtures — the same pipeline, run against ACTUAL Wan clips at zero quota.

Demo mode (`server/demo.py`) proves the orchestration, but its clips are synthetic
320x180 texture pans, so the deterministic tier was only ever exercised against a cartoon
of video. This runtime runs the SAME pipeline against REAL 1280x720 Wan output: real
clips, real stills, real OpenCV, real ffmpeg, real qwen-vl. Only the two text stages are
pinned — scripting and repair return fixed strings — and that is exactly what makes the
content-addressed cache hit: the clips are generated once, and every run afterwards
replays them for free. Pinned stages call no model, so they bill nothing and the ledger
says so.

The kill-shot is not staged, which is the whole point. Shot 1 asks for a rightward pan; Wan
returns a beautiful, plausible, STATIC shot — |v|=0.028 against a 0.4 threshold. Tier-A
catches it for zero tokens, the repaired prompt actually pans, and the retake certifies. A
human skimming that first clip would have shipped it; that is the product's thesis, executed
on real generated video.
(The measured numbers live in docs/verification.md, which is regenerated from a real run
rather than transcribed here — a docstring cannot be re-measured.)

Audio: Wan clips are silent, so the episode's sound is a real qwen-tts (CosyVoice) slate
per shot (server/tts.py), synthesized during the warm and replayed from cache afterwards —
so the certified episode carries a real voice, not a placeholder tone.

Warm the cache once (fresh quota, ~100s per clip):
    python scripts/warm_fixtures.py
Then run free, replaying real video:
    DAILIES_FIXTURES=1 SPA_DIST=web/dist uvicorn server.app:create_production_app --factory
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

from server.assemble import assemble
from server.metrics import LedgerWriter
from server.pipeline import Config, Deps
from server.store import Store
from server.tier_a import run_tier_a
from server.wan import WanClient

PREMISE = "a corgi pulls off a bread heist at a crowded farmers' market"

# Corgi, not coastal dusk, and the reason is the same one server/demo.py gives: a lighthouse
# at dusk hands `subject_present` a frame with exactly one thing in it. A short dog at knee
# height in a moving crowd is the case where the VLM can be WRONG — shoppers are subject
# distractors, and drifting ears and markings are a real test of `identity_consistent`. The
# low subject also motivates the pan the shot then fails to deliver.

# Shot 1, take 0. A sincere request for a rightward pan that Wan does not honour: the camera
# does not move at all, measured at |v|=0.028 against a 0.4 static threshold. Verbatim on
# purpose — this exact string is the cache key for the clip that fails, so it must never be
# "tidied".
#
# The wording was arrived at by measurement, not taste. An earlier version ended "...the
# camera pans steadily to the right, FOLLOWING THE DOG", and that one PASSED at
# camera_dx=+2.85: a subject moving laterally hands the model every reason to track, so the
# ask became self-fulfilling and the check had nothing left to catch. A failure is only worth
# showing if it is unstaged, which means the prompt must be a genuine request over a scene
# with no inherent lateral motion — the condition the coastal pack had, not the outcome.
# Chosen over a sibling candidate that panned the wrong way (dx=-4.07): that one is more
# dramatic, but in a frame full of moving shoppers a reader can wonder whether the crowd
# moved rather than the camera. 0.028 admits no such argument.
PAN_ASKED = (
    "A farmers' market bread stall at golden hour, wicker baskets of loaves, a corgi waiting "
    "quietly at the baker's feet with a roll in its mouth. The camera pans steadily to the "
    "right along the stalls, revealing the length of the market. Cinematic, continuous shot, "
    "no cuts."
)

# Shot 1, take 1 — what the repair stage rewrites the above into. Front-loads the camera
# move and forces lateral translation ("sliding in from the right edge of frame"), which
# is what actually shifts the frame rather than merely describing a shift.
PAN_REPAIRED = (
    "Fast lateral tracking shot moving right along a farmers' market aisle at knee height. "
    "The camera sweeps rightward at speed, market stalls and shoppers' legs rushing past "
    "the frame, a corgi carrying a bread roll sliding in from the right edge of frame. "
    "Strong continuous left-to-right camera movement, no cuts."
)

# Checks every shot carries. These are the four that behave identically on synthetic and
# real clips (verified on real Wan output: 5.37s, luma 95.4, flicker std 2.44, 0 cuts).
# camera_motion is asserted ONLY on shot 1 — it is the claim under test, not scenery.
_BASE_ASSERTIONS = [
    {"type": "duration_between", "params": {"min_s": 4.0, "max_s": 6.0}},
    {"type": "brightness_range", "params": {"min": 25, "max": 235}},
    {"type": "flicker_below", "params": {"max_std": 22.0}},
    {"type": "scene_cuts", "params": {"max": 1}},
]

_SHOTS = [
    {
        "prompt": ("A crowded Saturday farmers' market at golden hour, shoppers browsing wooden "
                   "stalls piled with bread and vegetables. Warm morning light. Cinematic, "
                   "locked-off camera, no cuts."),
        "narration": "Nine in the morning at the market. Two hundred customers, and one of them is not a customer.",
        "assertions": _BASE_ASSERTIONS,
    },
    {
        "prompt": PAN_ASKED,
        "narration": "Nobody ever looks down. That has always been the entire plan.",
        "speaker": "the corgi",
        # The subject checks ride the kill-shot on purpose: Tier-0 asks them of the still,
        # before this shot costs a single video second, and they are asked of the one frame
        # in the pack where a crowd gives the VLM a way to be wrong.
        "assertions": _BASE_ASSERTIONS + [
            {"type": "camera_motion", "params": {"direction": "right"}},
            {"type": "subject_present", "params": {"subject": "the corgi"}},
            {"type": "identity_consistent", "params": {"subject": "the corgi"}},
        ],
    },
    {
        "prompt": ("Close-up of a corgi dropping a bread roll at a baker's feet on cobblestones, "
                   "warm morning light, the baker's hands reaching down to take it. Cinematic, "
                   "no cuts."),
        "narration": "The roll always comes back. That is the arrangement.",
        "assertions": _BASE_ASSERTIONS,
    },
]


def _no_usage():
    """A pinned stage calls no model, so it bills nothing. The ledger records the truth
    rather than a plausible-looking number."""
    return SimpleNamespace(prompt_tokens=0, completion_tokens=0, total_tokens=0)


def fixture_shots(max_shots: int = 3) -> list[dict]:
    """Deep copies. compile_shots merges pack defaults into these dicts, and `params` is a
    nested dict — a shallow copy would let one run's merge mutate the module constant and
    leak into the next."""
    return deepcopy(_SHOTS[:max_shots])


def _fixture_script(premise, pack, max_shots):
    return fixture_shots(max_shots), _no_usage()


def _fixture_repair(spec, failures):
    """Pinned rewrite: the asked-for pan becomes the prompt that actually pans. Deterministic
    so the retake is a cache hit. Any other shot repairs to itself, which replays from cache
    and fails again — an honest dead end rather than a fake recovery."""
    if spec.prompt.strip() == PAN_ASKED.strip():
        return PAN_REPAIRED, _no_usage()
    return spec.prompt, _no_usage()


def build_fixture_runtime(data_dir: str | None = None):
    from openai import OpenAI

    from server.app import Runtime  # imported here to avoid a cycle at module load
    from server.config import settings
    from server.script import compile_custom_rules
    from server.tier_b import TierBVerifier
    from server.tier0 import Tier0Verifier
    from server.tts import TTSClient

    api_key = settings.QWEN_API_KEY
    root = Path(data_dir) if data_dir is not None else Path(settings.DATA_DIR)
    wan = WanClient(api_key, cache_dir=str(root / "cache"))
    tts = TTSClient(api_key, cache_dir=str(root / "cache"))
    llm = OpenAI(api_key=api_key, base_url=settings.QWEN_BASE_URL)
    cfg = Config(chat_model=settings.QWEN_CHAT_MODEL, vl_model=settings.VL_MODEL,
                 data_dir=str(root / "projects"))
    deps = Deps(
        script_fn=_fixture_script,
        gen_image_fn=lambda prompt: wan.generate_image(prompt),
        # Ungoverned on purpose: every clip here is a cache hit after warming, and the
        # judge-mode cap exists to stop FRESH spend. Warming is the one intentional spend.
        gen_video_fn=lambda prompt, model, negative_prompt=None: wan.generate_video(
            prompt, model=model, negative_prompt=negative_prompt),
        tier0_fn=Tier0Verifier(llm, model=settings.VL_MODEL),  # REAL qwen-vl on the real still
        tier_a_fn=run_tier_a,               # REAL deterministic CV, now on REAL video
        tier_b_fn=TierBVerifier(llm, model=settings.VL_MODEL),  # REAL qwen-vl on real frames
        repair_fn=_fixture_repair,
        # REAL qwen-plus compiling the user's plain-language rule into the closed vocabulary.
        # Wired here because this runtime is what the demo capture films: the request typed
        # on camera ends "must end on a title card", and with no compiler that rule was
        # accepted by the UI and then silently dropped — a check the viewer is told about and
        # never sees. title_card_present is Tier-B advisory, so a fail is honest and costs
        # the run nothing; only the two text stages above stay pinned, for cache reasons.
        custom_rule_fn=lambda rules: compile_custom_rules(
            rules, client=llm, model=settings.QWEN_CHAT_MODEL),
        assemble_fn=assemble,               # REAL ffmpeg
        ledger=LedgerWriter(root / "ledger.jsonl"),
        # Frame-anchored i2v — what makes a retake continue from the draft it fixes and the
        # certified final continue from the take that was approved, instead of re-rolling
        # from noise. Ungoverned like the rest of this runtime; warming is the one spend.
        patch_video_fn=lambda prompt, model, frame: wan.generate_video_from_frame(
            prompt, frame, model=model),
        # REAL qwen-tts (CosyVoice) narration; silent Wan clips get a spoken slate per
        # shot, synthesized once during the warm and cached like the clips.
        narrate_fn=tts.synthesize,
    )
    return Runtime(store=Store(str(root / "projects")), deps=deps, cfg=cfg, governor=None)
