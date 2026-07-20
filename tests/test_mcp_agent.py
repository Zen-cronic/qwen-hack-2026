"""The MCP loop, minus the LLM: spawn Dailies' MCP server over stdio and call it."""

import asyncio
import json
import sys

import pytest

from server.demo import _write_clip
from server.mcp_agent import mcp_config


def test_mcp_config_points_at_dailies_stdio_server():
    cfg = mcp_config()["mcpServers"]["dailies"]
    assert cfg["command"] == sys.executable
    assert cfg["args"] == ["-m", "server.mcp_server"]


def test_mcp_server_stdio_roundtrip(tmp_path):
    pytest.importorskip("mcp")
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    clip = tmp_path / "clip.mp4"
    _write_clip(clip, "right")

    async def run():
        params = StdioServerParameters(command=sys.executable, args=["-m", "server.mcp_server"])
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                names = [t.name for t in (await session.list_tools()).tools]
                res = await session.call_tool("run_shot_tests_tool", {
                    "video_path": str(clip),
                    "assertions": [{"type": "camera_motion", "params": {"direction": "right"}}],
                })
                text = "".join(getattr(c, "text", "") for c in res.content)
                blob = text or json.dumps(res.structuredContent or {})
                return names, blob

    names, blob = asyncio.run(run())
    assert "run_shot_tests_tool" in names
    assert "camera_motion" in blob and "passed" in blob
