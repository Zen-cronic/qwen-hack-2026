"""Real-video fixtures — the full pipeline on REAL Wan clips, free once the cache is warm.

Only the two text stages (scripting, repair) are pinned; warm with scripts/warm_fixtures.py.
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

# Shot 1, take 0 — a rightward pan Wan does not honour (|v|=0.028 vs a 0.4 threshold).
# Verbatim: this exact string is a cache key. Do not reword.
PAN_ASKED = (
    "A farmers' market bread stall at golden hour, wicker baskets of loaves, a corgi waiting "
    "quietly at the baker's feet with a roll in its mouth. The camera pans steadily to the "
    "right along the stalls, revealing the length of the market. Cinematic, continuous shot, "
    "no cuts."
)

# Shot 1, take 1 — the repaired prompt.
# Verbatim: this exact string is a cache key. Do not reword.
PAN_REPAIRED = (
    "Fast lateral tracking shot moving right along a farmers' market aisle at knee height. "
    "The camera sweeps rightward at speed, market stalls and shoppers' legs rushing past "
    "the frame, a corgi carrying a bread roll sliding in from the right edge of frame. "
    "Strong continuous left-to-right camera movement, no cuts."
)

# Checks every shot carries; camera_motion is asserted ONLY on shot 1 (the claim under test).
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
        # Tier-0 asks the subject checks of the still, before this shot costs a video second.
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
    """A pinned stage calls no model, so it bills nothing."""
    return SimpleNamespace(prompt_tokens=0, completion_tokens=0, total_tokens=0)


def fixture_shots(max_shots: int = 3) -> list[dict]:
    """Must deep-copy: compile_shots merges into these dicts, so a shallow copy mutates the module constant."""
    return deepcopy(_SHOTS[:max_shots])


def _fixture_script(premise, pack, max_shots):
    return fixture_shots(max_shots), _no_usage()


def _fixture_repair(spec, failures):
    """Pinned rewrite, deterministic so the retake is a cache hit; any other shot repairs to itself."""
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
        # Ungoverned on purpose: warming is the one intentional spend.
        gen_video_fn=lambda prompt, model, negative_prompt=None: wan.generate_video(
            prompt, model=model, negative_prompt=negative_prompt),
        tier0_fn=Tier0Verifier(llm, model=settings.VL_MODEL),  # REAL qwen-vl on the real still
        tier_a_fn=run_tier_a,               # REAL deterministic CV, now on REAL video
        tier_b_fn=TierBVerifier(llm, model=settings.VL_MODEL),  # REAL qwen-vl on real frames
        repair_fn=_fixture_repair,
        # REAL qwen-plus compiling plain-language rules into the closed vocabulary.
        custom_rule_fn=lambda rules: compile_custom_rules(
            rules, client=llm, model=settings.QWEN_CHAT_MODEL),
        assemble_fn=assemble,               # REAL ffmpeg
        ledger=LedgerWriter(root / "ledger.jsonl"),
        # Frame-anchored i2v: a retake continues from the draft it fixes rather than re-rolling.
        patch_video_fn=lambda prompt, model, frame: wan.generate_video_from_frame(
            prompt, frame, model=model),
        # REAL qwen-tts narration; silent Wan clips get a spoken slate per shot.
        narrate_fn=tts.synthesize,
    )
    return Runtime(store=Store(str(root / "projects")), deps=deps, cfg=cfg, governor=None)
