"""MCP server — gate generated video the way you gate code.

Exposes the Dailies conformance engine as an MCP tool so any pipeline or agent can
run shot tests against an authored spec. This is the "packs-as-data productization"
path made runnable: `run_shot_tests` uses only the deterministic Tier-A CV checks, so
it is zero-token, needs no API key, and runs on ANY mp4 — the model-agnostic claim,
executable rather than asserted.

The core `run_shot_tests` function imports no MCP dependency (so it is testable and
reusable on its own); the protocol server is built lazily in `main()`.

Run:  python -m server.mcp_server        (requires the extra: pip install -e ".[mcp]")

Roadmap tools (not yet exposed): compile_shot (NL -> validated assertions, needs an
LLM client) and get_conformance_report (read a project's state.json snapshot).
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

    Provide `assertions` (raw ``{"type", "params"}`` dicts) and/or `pack_name` (a
    ``packs/*.yaml`` of baseline checks); they merge with shot assertions overriding
    same-type pack defaults. Invented or malformed assertions are rejected before
    anything runs. Returns a conformance report with a pass/fail gate over the
    non-advisory checks. Deterministic, zero-token, any mp4.
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


def _build_server():
    """Construct the FastMCP server. Imported lazily so the core stays MCP-free."""
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("dailies")

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

    return server


def main() -> None:
    _build_server().run()  # stdio transport


if __name__ == "__main__":
    main()
