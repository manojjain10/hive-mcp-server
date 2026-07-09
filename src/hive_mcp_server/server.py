"""Cloudera Hive MCP Server — MCP registration layer.

This module intentionally stays thin: it wires the FastMCP server, loads
``.env`` before importing tools, and exposes each tool via a ``@mcp.tool()``
wrapper that delegates to the corresponding function in
``hive_mcp_server.tools.hive_tools``. All business logic (config, connection,
SQL safety, query execution) lives in that tools module.
"""

import os

from dotenv import load_dotenv
from fastmcp import FastMCP

# Load .env before importing tools so any code that reads env vars sees the
# values from a local .env file. When launched by an MCP client (which sets
# env vars directly), this is a no-op.
load_dotenv()

from hive_mcp_server.tools import hive_tools  # noqa: E402

mcp = FastMCP(name="Cloudera-Hive-Server")


@mcp.tool()
def list_databases() -> str:
    """Retrieve all available databases in the Hive Virtual Warehouse."""
    return hive_tools.list_databases()


@mcp.tool()
def list_tables(database: str) -> str:
    """Retrieve all tables for a given database."""
    return hive_tools.list_tables(database)


@mcp.tool()
def describe_table(database: str, table: str) -> str:
    """Return column names, types, and comments for `database`.`table`."""
    return hive_tools.describe_table(database, table)


@mcp.tool()
def get_table_sample(database: str, table: str, limit: int = 10) -> str:
    """Preview the first `limit` rows of `database`.`table` (1..100)."""
    return hive_tools.get_table_sample(database, table, limit)


@mcp.tool()
def execute_query(query: str) -> str:
    """Execute a HiveQL query and return results as JSON.

    When HIVE_READ_ONLY is true (the default), write DDL/DML is rejected.
    Results are capped at HIVE_QUERY_ROW_LIMIT rows.
    """
    return hive_tools.execute_query(query)


def main() -> None:
    """Console-script entry point invoked by ``hive-mcp-server`` / ``uvx``."""
    transport = os.getenv("MCP_TRANSPORT", "stdio")
    print(f"Starting Hive MCP Server via transport: {transport}")
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
