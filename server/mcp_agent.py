"""Close the MCP loop: a Qwen agent that consumes Dailies' own MCP server.

`build_mcp_agent()` returns a Qwen-Agent `Assistant` configured with Dailies'
`run_shot_tests` MCP server (`server/mcp_server.py`, launched over stdio) in its
`mcpServers` block — so a Qwen model calls the conformance tool *through* the Model
Context Protocol. Both ends are ours: the client (Qwen-Agent) and the server
(`server.mcp_server`). Needs the optional `[agent]` extra.

Run the whole loop live with `scripts/mcp_agent_demo.py` (chat tokens only, no video).
The MCP server subprocess is `python -m server.mcp_server`, so run from the repo root
(where `server` is importable).
"""

from __future__ import annotations

import sys
from typing import Any

from server.qwen_tools import qwen_llm_cfg

# The MCP server publishes patch_clip alongside run_shot_tests, and patch_clip spends a real
# i2v generation. Verification is free and comes first anyway, so the rail costs nothing and
# keeps a live demo from burning quota on a tool call nobody asked for.
SYSTEM = (
    "You are a video-QC assistant for Dailies. Use the run_shot_tests MCP tool to check a "
    "clip against a spec, then report whether it PASSED and name any failing checks. "
    "Never call patch_clip yourself — it spends generation quota. If a repair would help, "
    "say so and let the user ask for it."
)


def mcp_config() -> dict[str, Any]:
    """Qwen-Agent `mcpServers` block pointing at Dailies' own stdio MCP server."""
    return {
        "mcpServers": {
            "dailies": {"command": sys.executable, "args": ["-m", "server.mcp_server"]},
        }
    }


def build_mcp_agent():
    """A Qwen-Agent Assistant that reaches run_shot_tests via MCP. Lazy import."""
    from qwen_agent.agents import Assistant

    return Assistant(function_list=[mcp_config()], llm=qwen_llm_cfg(), system_message=SYSTEM)
