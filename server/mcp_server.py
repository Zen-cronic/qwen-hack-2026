"""MCP server exposing the Dailies conformance engine. Run: python -m server.mcp_server

The core functions must import no MCP dependency; the protocol server is built lazily.
"""

from __future__ import annotations

import tempfile
from typing import Any

from server.compiler import load_pack, merge_assertions
from server.specs import ShotSpec, Tier, parse_assertions
from server.tier_a import run_tier_a


def run_shot_tests(
    video_path: str,
    assertions: list[dict[str, Any]] | None = None,
    pack_name: str | None = None,
) -> dict[str, Any]:
    """Run deterministic Tier-A conformance checks on a clip against an authored spec.

    Takes raw ``{"type", "params"}`` assertions and/or a `pack_name`; returns a conformance
    report gated on the non-advisory checks. Deterministic, zero-token, any mp4.
    """
    checked = parse_assertions(list(assertions or []))  # closed-vocab gate, before running
    if pack_name:
        checked = merge_assertions(load_pack(pack_name).defaults, checked)
    spec = ShotSpec(index=0, prompt="(external clip)", assertions=checked)

    with tempfile.TemporaryDirectory() as evidence_dir:
        results = run_tier_a(video_path, spec, evidence_dir)

    report_checks = [
        {"type": r.type.value, "tier": r.tier.value, "advisory": r.advisory,
         "status": r.status.value, "detail": r.detail, "measured": r.measured}
        for r in results
    ]
    blocking_fail = [c for c in report_checks if not c["advisory"] and c["status"] == "fail"]
    # Tier-B (VLM) assertions can't run here — they need the full pipeline + an API key.
    vlm_skipped = [a.type.value for a in checked if a.tier is not Tier.TIER_A]

    return {
        "video_path": video_path,
        "passed": not blocking_fail,
        "checks": report_checks,
        "skipped_vlm_checks": vlm_skipped,
        "summary": {"total": len(report_checks), "failed": len(blocking_fail)},
    }


def patch_clip(
    video_path: str,
    assertions: list[dict[str, Any]] | None = None,
    pack_name: str | None = None,
    model: str | None = None,
    instruction: str | None = None,
) -> dict[str, Any]:
    """Repair a clip in place: re-render it from its last good frame, then re-verify.

    SPENDS quota (one 5s i2v/kf2v generation) and needs QWEN_API_KEY; a patch that still
    fails is reported as patched=false and leaves the original untouched.
    """
    from pathlib import Path
    from tempfile import mkdtemp

    from server.config import settings
    from server.patch import anchor_second, extract_frame, localized_failure
    from server.wan import WanClient

    before = run_shot_tests(video_path, assertions, pack_name)
    checked = parse_assertions(list(assertions or []))
    if pack_name:
        checked = merge_assertions(load_pack(pack_name).defaults, checked)
    spec = ShotSpec(index=0, prompt=instruction or "(external clip)", assertions=checked)

    work = Path(mkdtemp(prefix="dailies-patch-"))
    results = run_tier_a(video_path, spec, str(work))
    failure = localized_failure(results)
    if failure is None:
        return {**before, "patched": False,
                "reason": "no blocking failure with a located window"}

    at = anchor_second(failure)
    anchor = extract_frame(video_path, at, work / "anchor.png")
    if anchor is None:
        return {**before, "patched": False, "reason": f"could not read a frame at {at:.2f}s"}

    if not settings.QWEN_API_KEY:
        return {**before, "patched": False, "reason": "QWEN_API_KEY not set"}
    wan = WanClient(settings.QWEN_API_KEY, cache_dir=str(Path(settings.DATA_DIR) / "cache"))
    prompt = instruction or f"{spec.prompt} — fix: {failure.detail}"
    res = wan.generate_video_from_frame(prompt, anchor, model=model or "wan2.2-i2v-flash")
    if not res.ok:
        return {**before, "patched": False,
                "reason": f"generation failed: {res.code}: {res.message}"}

    after = run_shot_tests(res.local_path, assertions, pack_name)
    return {
        "patched": bool(after["passed"]),
        "reason": "patched and re-verified" if after["passed"] else "patch still fails its contract",
        "anchor_seconds": round(at, 2),
        "located_failure": failure.type.value,
        "original": {"video_path": video_path, "passed": before["passed"]},
        "patched_clip": {"video_path": res.local_path, "passed": after["passed"]},
        "before": before["checks"],
        "after": after["checks"],
    }


def _build_server():
    """Construct the FastMCP server. Imported lazily so the core stays MCP-free."""
    from mcp.server.fastmcp import FastMCP

    # Quiet by default: a stdio server logs to the client's stderr.
    server = FastMCP("dailies", log_level="WARNING")

    @server.tool()
    def run_shot_tests_tool(
        video_path: str,
        assertions: list[dict[str, Any]] | None = None,
        pack_name: str | None = None,
    ) -> dict[str, Any]:
        """Run Dailies Tier-A conformance checks on a video against an authored spec.

        video_path: path to an mp4. assertions: list of {type, params}. pack_name:
        optional baseline pack (e.g. "brand_rules"). Returns a conformance report."""
        return run_shot_tests(video_path, assertions, pack_name)

    @server.tool()
    def patch_clip_tool(
        video_path: str,
        assertions: list[dict[str, Any]] | None = None,
        pack_name: str | None = None,
        model: str | None = None,
        instruction: str | None = None,
    ) -> dict[str, Any]:
        """Repair a clip by re-rendering it from its last good frame, then re-verifying.

        Unlike the free run_shot_tests, this SPENDS one 5s i2v/kf2v generation and needs
        QWEN_API_KEY; patched=false if it still fails."""
        return patch_clip(video_path, assertions, pack_name, model, instruction)

    return server


def main() -> None:
    _build_server().run()  # stdio transport


if __name__ == "__main__":
    main()
