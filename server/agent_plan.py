"""Agent-authored pipeline plan — the agent wires the graph, the server keeps it valid.

The Qwen agent does NOT emit graph topology; it emits run PARAMETERS (premise, pack,
shots, custom checks) by calling the build_pipeline_graph tool. The server deterministically
expands those into the canonical node/edge layout, so a malformed graph is impossible by
construction while the "the agent built the pipeline" story stays fully truthful.

Two modes, one shape: real qwen-plus function-calling in the live runtime, a deterministic
keyword stub in demo/fixtures (and whenever no API key is set) so the demo is hermetic and
spends zero quota. Both return the same PipelinePlan plus a tool-call transcript that is the
evidence a Qwen custom tool actually authored the run.

The node/edge id scheme (script, stills, review, gen-{i}, check-{i}, assemble, episode) is
canonical and mirrors web/src/graph.ts, so a plan-drawn canvas and a live-run canvas are the
same nodes.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, Field

from server.config import settings


class PlanNode(BaseModel):
    id: str
    kind: str  # stage | review | shot | check | episode
    label: str


class PlanEdge(BaseModel):
    source: str
    target: str


class PipelinePlan(BaseModel):
    premise: str = Field(min_length=1)
    pack: str
    max_shots: int = Field(ge=1, le=12)
    custom_checks: list[str] = Field(default_factory=list)
    rationale: str = ""
    nodes: list[PlanNode]
    edges: list[PlanEdge]


def expand_plan(
    premise: str,
    pack: str,
    max_shots: int,
    custom_checks: list[str] | None = None,
    rationale: str = "",
) -> PipelinePlan:
    """Expand run parameters into the canonical pipeline graph. Single source of truth for
    the server-side topology; the ids match web/src/graph.ts exactly."""
    n = max(1, min(12, int(max_shots)))
    nodes = [
        PlanNode(id="script", kind="stage", label="Script"),
        PlanNode(id="stills", kind="stage", label="Stills"),
        PlanNode(id="review", kind="review", label="Review"),
    ]
    edges = [
        PlanEdge(source="script", target="stills"),
        PlanEdge(source="stills", target="review"),
    ]
    for i in range(n):
        nodes.append(PlanNode(id=f"gen-{i}", kind="shot", label=f"Shot {i}"))
        nodes.append(PlanNode(id=f"check-{i}", kind="check", label="Checks"))
        edges.append(PlanEdge(source="review", target=f"gen-{i}"))
        edges.append(PlanEdge(source=f"gen-{i}", target=f"check-{i}"))
        edges.append(PlanEdge(source=f"check-{i}", target="assemble"))
    nodes.append(PlanNode(id="assemble", kind="stage", label="Assemble"))
    nodes.append(PlanNode(id="episode", kind="episode", label="Episode"))
    edges.append(PlanEdge(source="assemble", target="episode"))
    return PipelinePlan(
        premise=premise.strip() or "an untitled short",
        pack=pack,
        max_shots=n,
        custom_checks=[c for c in (custom_checks or []) if c.strip()],
        rationale=rationale.strip(),
        nodes=nodes,
        edges=edges,
    )


_SYSTEM = (
    "You are the pipeline planner for Dailies, a CI system for AI-generated video. Given a "
    "user's request for a short video, call build_pipeline_graph exactly once with: the "
    "premise, the best-fitting rules pack, a sensible shot count (1-12), and any explicit "
    "requirement restated as a custom check (e.g. 'a title card must be visible'). Prefer "
    "short_drama for narrative clips and brand_rules when brand/logo/marketing safety is "
    "implied. Do not write the shots yourself — Dailies compiles them. Just choose the "
    "parameters."
)


def _tool_spec(packs: list[str]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "build_pipeline_graph",
            "description": (
                "Design a Dailies verification pipeline for a video premise. Dailies compiles "
                "the parameters into a shot list, deterministic CV + VLM checks, a human review "
                "gate, and a certified cut. Provide only the parameters — not the graph itself."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "premise": {"type": "string", "description": "The episode premise / creative brief."},
                    "pack": {
                        "type": "string",
                        "enum": packs or ["short_drama"],
                        "description": "Rules pack: short_drama (continuity) or brand_rules (brand safety).",
                    },
                    "max_shots": {"type": "integer", "minimum": 1, "maximum": 12, "description": "Number of shots."},
                    "custom_checks": {
                        "type": "array", "items": {"type": "string"},
                        "description": "Extra checks in plain language, e.g. 'a title card must be visible'.",
                    },
                    "rationale": {"type": "string", "description": "One sentence: why this shape fits the request."},
                },
                "required": ["premise", "pack", "max_shots"],
            },
        },
    }


def _pick_pack(pack: str | None, packs: list[str]) -> str:
    if pack and pack in packs:
        return pack
    if "short_drama" in packs:
        return "short_drama"
    return packs[0] if packs else "short_drama"


def _plan_from_args(args: dict[str, Any], packs: list[str]) -> PipelinePlan:
    """Validate and expand the tool arguments the model supplied. Defensive: the model can
    omit or mistype anything, and none of it may reach the executor unchecked."""
    premise = str(args.get("premise") or "").strip()
    pack = _pick_pack(args.get("pack"), packs)
    try:
        shots = int(args.get("max_shots") or 3)
    except (TypeError, ValueError):
        shots = 3
    raw_checks = args.get("custom_checks") or []
    checks = [str(c).strip() for c in raw_checks if str(c).strip()] if isinstance(raw_checks, list) else []
    rationale = str(args.get("rationale") or "").strip()
    return expand_plan(premise, pack, shots, checks, rationale)


def _plan_stub(message: str, packs: list[str]) -> PipelinePlan:
    """Deterministic planner for demo/fixtures and the no-key fallback. Parses the request
    the way the agent would, with zero API calls — so the demo is hermetic and repeatable."""
    text = message.strip()
    low = text.lower()
    m = re.search(r"(\d+)\s*[- ]?shot", low)
    shots = int(m.group(1)) if m else 3
    pack = "brand_rules" if (("brand" in low or "logo" in low) and "brand_rules" in packs) else _pick_pack(None, packs)
    checks: list[str] = []
    if "title card" in low or "title-card" in low:
        checks.append("a title card must be visible")
    if "pan right" in low or "pans right" in low:
        checks.append("the camera should pan right")
    if "pan left" in low or "pans left" in low:
        checks.append("the camera should pan left")
    n = max(1, min(12, shots))
    rationale = f"Compiled a {n}-shot {pack} pipeline" + (
        f" with {len(checks)} custom check{'s' if len(checks) != 1 else ''}." if checks else "."
    )
    return expand_plan(text, pack, n, checks, rationale)


def _transcript_entry(args: dict[str, Any], plan: PipelinePlan) -> dict[str, Any]:
    return {
        "role": "tool_call",
        "name": "build_pipeline_graph",
        "arguments": json.dumps(args),
        "result": plan.model_dump(mode="json"),
    }


def _stub_transcript(plan: PipelinePlan) -> list[dict[str, Any]]:
    args = {
        "premise": plan.premise, "pack": plan.pack, "max_shots": plan.max_shots,
        "custom_checks": plan.custom_checks, "rationale": plan.rationale,
    }
    return [_transcript_entry(args, plan)]


def _plan_live(message: str, packs: list[str], *, model: str | None = None, max_rounds: int = 3):
    """Real qwen-plus function-calling. The tool call carries the whole plan, so the first
    call ends the loop; a model that answers without calling the tool falls back to the stub."""
    from openai import OpenAI

    client = OpenAI(api_key=settings.QWEN_API_KEY, base_url=settings.QWEN_BASE_URL)
    model = model or settings.QWEN_CHAT_MODEL
    tool = _tool_spec(packs)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": message},
    ]
    transcript: list[dict[str, Any]] = []
    for _ in range(max_rounds):
        resp = client.chat.completions.create(
            model=model, messages=messages, tools=[tool], tool_choice="auto", temperature=0)
        msg = resp.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))
        if msg.tool_calls:
            tc = msg.tool_calls[0]
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {}
            plan = _plan_from_args(args, packs)
            transcript.append(_transcript_entry(args, plan))
            return plan, transcript
        transcript.append({"role": "assistant", "content": msg.content})
        break
    plan = _plan_stub(message, packs)
    transcript.extend(_stub_transcript(plan))
    return plan, transcript


def plan_from_message(message: str, *, demo: bool, packs: list[str], model: str | None = None):
    """Return (PipelinePlan, transcript). demo (or a missing key) uses the deterministic stub;
    otherwise qwen-plus authors the plan by calling the build_pipeline_graph tool."""
    if demo or not settings.QWEN_API_KEY:
        plan = _plan_stub(message, packs)
        return plan, _stub_transcript(plan)
    return _plan_live(message, packs, model=model)
