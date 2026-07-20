"""Demo: a Qwen agent calls Dailies' conformance gate THROUGH the Model Context Protocol.

Builds a Qwen-Agent Assistant with Dailies' own MCP server in its mcpServers block, then
asks it to verify a clip — the model discovers the tools over MCP, picks one, and calls it
(client + server both ours). Chat tokens only, no video quota.

The transcript is printed as it happens: ListTools, the CallTool the model chose with its
real arguments, the server's verdict, then the answer. Nothing here is narrated on the
model's behalf — every line is a message that crossed the protocol.

Run from the repo root:  python scripts/mcp_agent_demo.py [clip.mp4]
Requires the [agent] extra (pip install -e ".[agent]") and a QWEN_API_KEY in .env.
"""

import json
import logging
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root on path

from server.mcp_agent import build_mcp_agent

# The clip asserts a rightward pan and doesn't deliver one: the same kill-shot the
# workbench catches in Act 1, reaching an agent this time. A gate is only worth watching
# when it catches something.
ASSERTIONS = [{"type": "camera_motion", "params": {"direction": "right"}}]
PACK = "brand_rules"

# ANSI, so the beat reads on camera. Dim is the protocol's own bookkeeping; the verdict
# is the only thing that gets a color of its own.
DIM, BOLD, OFF = "\033[2m", "\033[1m", "\033[0m"
BLUE, GREEN, RED, AMBER, VIOLET = (
    "\033[38;5;75m", "\033[38;5;114m", "\033[38;5;203m", "\033[38;5;179m", "\033[38;5;141m",
)


def _get_clip(argv: list[str]) -> str:
    if len(argv) > 1:
        return argv[1]
    from server.demo import _write_clip
    clip = Path(tempfile.mkdtemp()) / "shot.mp4"
    _write_clip(clip, "static")  # asserts a pan, renders static — a real, measured failure
    return str(clip)


def _field(msg, key: str):
    return msg.get(key) if isinstance(msg, dict) else getattr(msg, key, None)


def _content(msg) -> str:
    c = _field(msg, "content") or ""
    return c if isinstance(c, str) else str(c)


def _print_tools(agent) -> None:
    """What the agent learned over MCP before it said anything — a real ListTools result."""
    print(f"{DIM}  MCP ListTools{OFF}  {BOLD}dailies{OFF}")
    for name in agent.function_map:
        # patch_clip is the acting counterpart to the reporting one, and it spends.
        cost = "spends one i2v generation" if "patch" in name else "free · deterministic · any mp4"
        print(f"      {AMBER}{name}{OFF}  {DIM}{cost}{OFF}")
    print()


def _print_call(call) -> None:
    args = _field(call, "arguments") or "{}"
    try:  # re-dump so long argument blobs wrap predictably on a projector
        args = json.dumps(json.loads(args), separators=(", ", ": "))
    except (TypeError, ValueError):
        pass
    print(f"  {GREEN}qwen-plus{OFF}  {DIM}→ MCP CallTool{OFF}  {AMBER}{_field(call, 'name')}{OFF}")
    print(f"      {DIM}{args}{OFF}")


def _print_result(msg) -> None:
    """The server's own report, unedited — parsed only to pull the verdict forward."""
    try:
        report = json.loads(_content(msg))
    except ValueError:
        print(f"  {BLUE}dailies-mcp{OFF}  {_content(msg)[:200]}")
        return
    passed = report.get("passed")
    verdict = f"{GREEN}PASS{OFF}" if passed else f"{RED}FAIL{OFF}"
    summary = report.get("summary", {})
    tally = f"{summary.get('failed', 0)} of {summary.get('total', 0)} checks failed"
    print(f"  {BLUE}dailies-mcp{OFF}  {DIM}→ run_shot_tests →{OFF} {verdict}  {DIM}{tally}{OFF}")
    for c in report.get("checks", []):
        if c.get("status") == "fail" and not c.get("advisory"):
            print(f"      {VIOLET}{c['type']}{OFF} · {c.get('detail', '')}")
    print()


def main() -> None:
    logging.disable(logging.INFO)  # qwen-agent narrates its own plumbing at INFO
    clip = _get_clip(sys.argv)
    prompt = (f"Verify the clip at {clip}. It must pan right, and it must satisfy the "
              f"{PACK} pack. Pass these assertions: {json.dumps(ASSERTIONS)}. "
              f"Did it pass, and which checks failed?")

    print(f"\n{BOLD}Dailies — Qwen agent → MCP → run_shot_tests{OFF}")
    print(f"{DIM}  a Qwen agent connects to Dailies' own MCP server over stdio")
    print(f"  (client + server both ours), lists tools, then:{OFF}\n")

    agent = build_mcp_agent()
    _print_tools(agent)
    print(f"  {BOLD}user{OFF}       the shot must pan right, on the {PACK} pack — verify it\n")

    seen = 0
    responses: list = []
    for responses in agent.run([{"role": "user", "content": prompt}]):
        # run() yields the whole response so far, re-emitting the tail as it streams. Only
        # messages a later one has displaced are finished, so the last stays pending.
        for msg in responses[seen:max(seen, len(responses) - 1)]:
            if _field(msg, "function_call"):
                _print_call(_field(msg, "function_call"))
            elif _field(msg, "role") == "function":
                _print_result(msg)
        seen = max(seen, len(responses) - 1)

    answer = _content(responses[-1]) if responses else "(no output)"
    print(f"  {GREEN}qwen-plus{OFF}  {answer.strip()}\n")
    print(f"{DIM}  a full Model Context Protocol round-trip — both ends are Dailies.{OFF}\n")


if __name__ == "__main__":
    main()
