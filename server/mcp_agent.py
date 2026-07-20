"""A Qwen agent that consumes Dailies' own MCP server over stdio. Needs the `[agent]` extra.

Run from the repo root — the server subprocess is `python -m server.mcp_server`.
"""

from __future__ import annotations

import sys
from typing import Any

from server.qwen_tools import qwen_llm_cfg

# The patch_clip rail below is deliberate: that tool spends a real i2v generation.
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
