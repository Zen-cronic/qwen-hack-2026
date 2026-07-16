"""Real-video fixtures — the same pipeline, run against ACTUAL Wan clips at zero quota.

Demo mode (`server/demo.py`) proves the orchestration, but its clips are synthetic
320x180 texture pans, so the deterministic tier was only ever exercised against a cartoon
of video. This runtime runs the SAME pipeline against REAL 1280x720 Wan output: real
clips, real stills, real OpenCV, real ffmpeg, real qwen-vl. Only the two text stages are
pinned — scripting and repair return fixed strings — and that is exactly what makes the
content-addressed cache hit: the clips are generated once, and every run afterwards
replays them for free. Pinned stages call no model, so they bill nothing and the ledger
says so.

The kill-shot is not staged, which is the whole point. Shot 1 asks for a rightward pan;
Wan returns a beautiful, plausible, STATIC shot — measured |v|=0.34 against a 0.4 static
threshold, corroborated by phase correlation at dx=-0.02px across the entire clip. Tier-A
catches it for zero tokens, the repaired prompt actually pans (|v|=1.47, detected
"right"), and the retake certifies. A human skimming that first clip would have shipped
it; that is the product's thesis, executed on real generated video.

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

PREMISE = "a lonely lighthouse keeper who discovers a message in a bottle"

# Shot 1, take 0. Asks politely for a pan; Wan ignores the camera instruction and returns
# a static shot. Verbatim on purpose — this exact string is the cache key for the clip
# that fails, so it must never be "tidied".
PAN_ASKED = (
    "A lighthouse on a rocky cliff at dusk. The camera pans steadily to the right "
    "across the cliff face, revealing the sea. Cinematic, continuous shot, no cuts."
)

# Shot 1, take 1 — what the repair stage rewrites the above into. Front-loads the camera
# move and forces lateral translation ("sliding in from the right edge of frame"), which
# is what actually shifts the frame rather than merely describing a shift.
PAN_REPAIRED = (
    "Aerial tracking shot flying fast to the right along a rocky coastline at dusk. "
    "The camera sweeps laterally rightward at speed, cliffs rushing past the frame, "
    "a lighthouse sliding in from the right edge of frame. Strong continuous "
    "left-to-right camera movement, no cuts."
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
        "prompt": ("A weathered lighthouse keeper stands at a rain-streaked window at dusk, "
                   "looking out at a grey sea. Warm lamp light on his face. Cinematic, no cuts."),
        "assertions": _BASE_ASSERTIONS,
    },
    {
        "prompt": PAN_ASKED,
        "assertions": _BASE_ASSERTIONS + [{"type": "camera_motion", "params": {"direction": "right"}}],
    },
    {
        "prompt": ("A glass bottle holding a rolled paper note, washed up among wet dark rocks "
                   "at dusk, small waves lapping around it. Cinematic, no cuts."),
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
    from server.tier_b import TierBVerifier
    from server.tier0 import Tier0Verifier

    api_key = settings.QWEN_API_KEY
    root = Path(data_dir) if data_dir is not None else Path(settings.DATA_DIR)
    wan = WanClient(api_key, cache_dir=str(root / "cache"))
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
        assemble_fn=assemble,               # REAL ffmpeg
        ledger=LedgerWriter(root / "ledger.jsonl"),
    )
    return Runtime(store=Store(str(root / "projects")), deps=deps, cfg=cfg, governor=None)
