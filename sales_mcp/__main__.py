"""Run Sales MCP: `python -m sales_mcp` (stdio locally, SSE when PORT is set)."""

import os

from sales_mcp.app import mcp

if __name__ == "__main__":
    port_env = os.getenv("PORT")
    if port_env:
        mcp.run(transport="sse", host="0.0.0.0", port=int(port_env))
    else:
        mcp.run(transport="stdio")
