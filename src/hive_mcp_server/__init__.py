"""Cloudera Hive MCP Server.

Exposes a Cloudera Data Warehouse Virtual Warehouse (Hive) to any MCP client
(Claude Desktop, Claude Code, Claude Agent SDK, LangChain MCP, etc.) as a set
of read-only tools by default. Set HIVE_READ_ONLY=false to allow write DDL/DML.

Entry point: `hive-mcp-server` (see pyproject.toml [project.scripts]).
"""

__version__ = "0.1.0"

from .server import main, mcp

__all__ = ["main", "mcp", "__version__"]
