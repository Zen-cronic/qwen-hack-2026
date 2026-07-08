"""Demo: a Qwen agent calls Dailies' conformance checker THROUGH the Model Context Protocol.

Builds a Qwen-Agent Assistant with Dailies' own run_shot_tests MCP server in its mcpServers
block, then asks it to check a clip — the model invokes the tool over MCP (client + server
both ours). Chat tokens only, no video quota.

Run from the repo root:  python scripts/mcp_agent_demo.py [clip.mp4]
Requires the [agent] extra (pip install -e ".[agent]") and a QWEN_API_KEY in .env.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root on path

from server.mcp_agent import build_mcp_agent


def _get_clip(argv: list[str]) -> str:
    if len(argv) > 1:
        return argv[1]
    from server.demo import _write_clip
    clip = Path(tempfile.mkdtemp()) / "demo_clip.mp4"
    _write_clip(clip, "right")
    return str(clip)


def _content(msg) -> str:
    c = msg["content"] if isinstance(msg, dict) else getattr(msg, "content", "")
    return c if isinstance(c, str) else str(c)


def main() -> None:
    clip = _get_clip(sys.argv)
    prompt = (f"Use the run_shot_tests tool to check the clip at {clip} with the brand_rules "
              f"pack. Did it pass, and which checks failed?")
    print("=== Qwen agent calling run_shot_tests THROUGH MCP (client + server both Dailies) ===")
    agent = build_mcp_agent()
    responses = list(agent.run([{"role": "user", "content": prompt}]))
    final_msgs = responses[-1] if responses else []
    print("ANSWER:", _content(final_msgs[-1]) if final_msgs else "(no output)")


if __name__ == "__main__":
    main()
