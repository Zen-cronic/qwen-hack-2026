"""Demo: run_shot_tests exposed as a Qwen custom tool — two native shapes.

Drives qwen-plus to call the Dailies conformance checker as a tool, first via native
function calling (OpenAI-compatible endpoint) and then via a Qwen-Agent Assistant custom
tool. Spends only chat tokens — no video quota.

Usage:
    python scripts/qwen_tool_demo.py [clip.mp4]      # generates a synthetic clip if omitted

Requires a QWEN_API_KEY in .env and the [agent] extra for the Assistant path
(pip install -e ".[agent]").
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root on path

from server.qwen_tools import build_conformance_agent, call_with_function_calling


def _get_clip(argv: list[str]) -> str:
    if len(argv) > 1:
        return argv[1]
    from server.demo import _write_clip  # local synthetic clip, zero quota
    clip = Path(tempfile.mkdtemp()) / "demo_clip.mp4"
    _write_clip(clip, "right")
    return str(clip)


def _content(msg) -> str:
    c = msg["content"] if isinstance(msg, dict) else getattr(msg, "content", "")
    return c if isinstance(c, str) else str(c)


def main() -> None:
    clip = _get_clip(sys.argv)
    prompt = (f"Run the conformance checks on the clip at {clip} using the brand_rules pack. "
              f"Did it pass, and which checks failed?")

    print("=== 1. Native function calling (qwen-plus, OpenAI-compatible endpoint) ===")
    final, transcript = call_with_function_calling(prompt)
    for step in transcript:
        if step["role"] == "tool_call":
            print(f"  → model called {step['name']}({step['arguments']})")
            print(f"    tool returned: {step['result'][:160]}...")
    print(f"  ANSWER: {final}\n")

    print("=== 2. Qwen-Agent custom tool (Assistant) ===")
    agent = build_conformance_agent()
    responses = list(agent.run([{"role": "user", "content": prompt}]))
    final_msgs = responses[-1] if responses else []
    answer = _content(final_msgs[-1]) if final_msgs else "(no output)"
    print(f"  ANSWER: {answer}")


if __name__ == "__main__":
    main()
