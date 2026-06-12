"""MCP server entry point. Exposes FL Studio control tools to the LLM."""

from __future__ import annotations

import threading

from fastmcp import FastMCP

from .client import BridgeClient, BridgeUnavailable

_client: BridgeClient | None = None
_client_lock = threading.Lock()


def get_client() -> BridgeClient:
    # Double-checked: FastMCP runs sync tools in worker threads, so two
    # concurrent tool calls could otherwise both construct a client.
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = BridgeClient()
    return _client


def build_server() -> FastMCP:
    mcp = FastMCP("fl-studio-mcp")

    @mcp.tool()
    def fl_ping() -> dict:
        """Check that FL Studio is running and the bridge is reachable."""
        try:
            result = get_client().call("meta.ping")
            return {"connected": True, "bridge": result}
        except BridgeUnavailable as exc:
            return {"connected": False, "error": str(exc)}

    return mcp


def main():
    build_server().run()
