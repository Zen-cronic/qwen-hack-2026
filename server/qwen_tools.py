"""Expose the Dailies conformance checker as a Qwen tool, in two shapes: native
function-calling (RUN_SHOT_TESTS_TOOL) and a Qwen-Agent BaseTool.

`run_shot_tests_json` must import neither `openai` nor `qwen_agent` — the wrappers do so lazily.
"""

from __future__ import annotations

import json
from typing import Any

from server.config import settings
from server.mcp_server import run_shot_tests

# JSON-Schema tool spec for the OpenAI-compatible / DashScope function-calling API.
RUN_SHOT_TESTS_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "run_shot_tests",
        "description": (
            "Run Dailies deterministic conformance checks (Tier-A computer vision) on a video "
            "clip against an authored spec. Zero-token, model-agnostic, works on any mp4. "
            "Returns a conformance report with a pass/fail gate over the non-advisory checks."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "video_path": {"type": "string", "description": "Path to the mp4 clip to test."},
                "assertions": {
                    "type": "array",
                    "description": "Assertion dicts {type, params} from the closed vocabulary "
                                   "(e.g. duration_between, camera_motion, palette_deltae).",
                    "items": {"type": "object"},
                },
                "pack_name": {
                    "type": "string",
                    "description": "Optional assertion pack whose baseline checks are merged in "
                                   "(e.g. 'brand_rules', 'short_drama').",
                },
            },
            "required": ["video_path"],
        },
    },
}

# Natural-language parameter list for the Qwen-Agent BaseTool form (same contract).
_QWEN_AGENT_PARAMS = [
    {"name": "video_path", "type": "string", "description": "Path to the mp4 clip to test.", "required": True},
    {"name": "assertions", "type": "array", "description": "Assertion dicts {type, params} from the closed vocabulary.", "required": False},
    {"name": "pack_name", "type": "string", "description": "Optional assertion pack (e.g. 'brand_rules').", "required": False},
]


def run_shot_tests_json(params: str | dict[str, Any]) -> str:
    """Parse LLM-supplied tool arguments (JSON string or dict) and return a JSON report."""
    args = json.loads(params) if isinstance(params, str) else dict(params)
    report = run_shot_tests(
        args["video_path"],
        assertions=args.get("assertions"),
        pack_name=args.get("pack_name"),
    )
    return json.dumps(report)


_SYSTEM = (
    "You are a video-QC assistant for Dailies. When asked to check a clip, call the "
    "run_shot_tests tool with the clip path and any requested assertions or pack, then "
    "report whether it PASSED and name any failing checks with their measured values."
)


def call_with_function_calling(user_message: str, *, model: str | None = None, max_rounds: int = 4):
    """Run a native function-calling loop against qwen-plus. Returns (final_text, transcript)."""
    from openai import OpenAI

    client = OpenAI(api_key=settings.QWEN_API_KEY, base_url=settings.QWEN_BASE_URL)
    model = model or settings.QWEN_CHAT_MODEL
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": user_message},
    ]
    transcript: list[dict[str, Any]] = []
    for _ in range(max_rounds):
        resp = client.chat.completions.create(
            model=model, messages=messages, tools=[RUN_SHOT_TESTS_TOOL], temperature=0)
        msg = resp.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))
        if not msg.tool_calls:
            transcript.append({"role": "assistant", "content": msg.content})
            return msg.content, transcript
        for tc in msg.tool_calls:
            result = run_shot_tests_json(tc.function.arguments)
            transcript.append({"role": "tool_call", "name": tc.function.name,
                               "arguments": tc.function.arguments, "result": result})
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
    return None, transcript


def register_qwen_agent_tool():
    """Register `run_shot_tests` as a Qwen-Agent custom tool (BaseTool). Lazy import."""
    from qwen_agent.tools.base import BaseTool, register_tool

    @register_tool("run_shot_tests", allow_overwrite=True)
    class RunShotTests(BaseTool):
        description = RUN_SHOT_TESTS_TOOL["function"]["description"]
        parameters = _QWEN_AGENT_PARAMS

        def call(self, params: str | dict, **kwargs) -> str:
            return run_shot_tests_json(params)

    return RunShotTests


def qwen_llm_cfg() -> dict[str, Any]:
    """Qwen-Agent llm config pointed at Dailies' OpenAI-compatible Qwen endpoint."""
    return {
        "model": settings.QWEN_CHAT_MODEL,
        "model_server": settings.QWEN_BASE_URL,
        "api_key": settings.QWEN_API_KEY,
        "generate_cfg": {"temperature": 0, "fncall_prompt_type": "nous"},
    }


def build_conformance_agent():
    """Build a Qwen-Agent Assistant wired with the run_shot_tests custom tool. Lazy import."""
    from qwen_agent.agents import Assistant

    register_qwen_agent_tool()
    return Assistant(function_list=["run_shot_tests"], llm=qwen_llm_cfg(), system_message=_SYSTEM)
