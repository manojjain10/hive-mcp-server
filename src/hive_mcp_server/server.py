"""Cloudera Hive MCP Server implementation.

Configuration is read from environment variables (or a local `.env` file, if
present). Required: HIVE_HOST, HIVE_USERNAME, HIVE_PASSWORD. Optional:
HIVE_PORT (443), HIVE_HTTP_PATH (/cliservice), HIVE_READ_ONLY (true),
HIVE_QUERY_ROW_LIMIT (1000).
"""

from __future__ import annotations

import base64
import os
import re

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from pyhive import hive
from thrift.transport import THttpClient

# Load .env if present in cwd. When the server is launched by an MCP client
# (which sets env vars in its config), this is a no-op.
load_dotenv()

# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

_WRITE_KEYWORDS = frozenset(
    {
        "insert",
        "update",
        "delete",
        "drop",
        "alter",
        "truncate",
        "create",
        "replace",
        "merge",
        "grant",
        "revoke",
        "msck",
        "load",
        "export",
        "import",
    }
)

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _cfg() -> dict:
    """Read config from env each call.

    Read-per-call (rather than at import) lets `uvx hive-mcp-server` fail with
    a clear error at run time when creds are missing, instead of exploding at
    import — important because MCP clients import this module *before* the
    subprocess env is fully wired in some setups.
    """
    port = int(os.getenv("HIVE_PORT", "443"))
    return {
        "host": os.getenv("HIVE_HOST"),
        "port": port,
        "path": os.getenv("HIVE_HTTP_PATH", "/cliservice"),
        "username": os.getenv("HIVE_USERNAME"),
        "password": os.getenv("HIVE_PASSWORD"),
        "read_only": os.getenv("HIVE_READ_ONLY", "true").strip().lower()
        in ("1", "true", "yes", "on"),
        "row_limit": int(os.getenv("HIVE_QUERY_ROW_LIMIT", "1000")),
    }


def _require_creds(cfg: dict) -> None:
    missing = [k for k in ("host", "username", "password") if not cfg[k]]
    if missing:
        names = ", ".join(f"HIVE_{m.upper()}" for m in missing)
        raise RuntimeError(
            f"Missing required environment variable(s): {names}. Set them in "
            "the MCP client config or in a .env file next to the working "
            "directory."
        )


mcp = FastMCP("Cloudera-Hive-Server")


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _get_hive_connection():
    """Open a fresh pyhive connection over HTTPS with LDAP/Basic auth.

    Cloudera Virtual Warehouses expect a Basic-auth `Authorization` header on
    a THttpClient transport. Connections are per-call: pyhive connections are
    not thread-safe and MCP tool invocations are short-lived, so pooling would
    add complexity for no measurable benefit at this scale.
    """
    cfg = _cfg()
    _require_creds(cfg)

    scheme = "https" if cfg["port"] == 443 else "http"
    uri = f"{scheme}://{cfg['host']}:{cfg['port']}{cfg['path']}"

    transport = THttpClient.THttpClient(uri)
    auth = f"{cfg['username']}:{cfg['password']}".encode("utf-8")
    b64 = base64.b64encode(auth).decode("utf-8")
    transport.setCustomHeaders({"Authorization": f"Basic {b64}"})

    return hive.Connection(thrift_transport=transport)


def _quote_ident(name: str) -> str:
    """Validate that `name` is a bare SQL identifier and return it unchanged.

    Tool arguments (database/table names) are interpolated into SQL. Anything
    outside `[A-Za-z_][A-Za-z0-9_]*` is rejected to prevent injection from a
    hostile or hallucinating LLM caller.
    """
    if not isinstance(name, str) or not _IDENT_RE.match(name):
        raise ValueError(
            f"Invalid identifier: {name!r}. Must match [A-Za-z_][A-Za-z0-9_]*."
        )
    return name


def _strip_sql_comments(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    sql = re.sub(r"--[^\n]*", " ", sql)
    return sql.strip()


def _is_read_only(sql: str) -> bool:
    """Return True if the first SQL keyword is not a write keyword."""
    cleaned = _strip_sql_comments(sql).lower()
    if not cleaned:
        return True
    first = cleaned.split(None, 1)[0]
    return first not in _WRITE_KEYWORDS


def _run(sql: str, row_limit: int | None = None) -> list[dict]:
    """Execute `sql` and return rows as list-of-dict, capped by `row_limit`."""
    conn = _get_hive_connection()
    try:
        cursor = conn.cursor()
        try:
            cursor.execute(sql)
            columns = [desc[0] for desc in (cursor.description or [])]
            if row_limit is None:
                rows = cursor.fetchall()
            else:
                rows = cursor.fetchmany(row_limit)
            return [dict(zip(columns, row)) for row in rows]
        finally:
            cursor.close()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def list_databases() -> list[str]:
    """Retrieve all available databases in the Hive Virtual Warehouse."""
    rows = _run("SHOW DATABASES")
    return [next(iter(row.values())) for row in rows]


@mcp.tool()
def list_tables(database: str) -> list[str]:
    """Retrieve all tables for a given database."""
    db = _quote_ident(database)
    rows = _run(f"SHOW TABLES IN {db}")
    return [next(iter(row.values())) for row in rows]


@mcp.tool()
def describe_table(database: str, table: str) -> list[dict]:
    """Return column names, types, and comments for `database`.`table`."""
    db = _quote_ident(database)
    tbl = _quote_ident(table)
    return _run(f"DESCRIBE {db}.{tbl}")


@mcp.tool()
def get_table_sample(
    database: str, table: str, limit: int = 10
) -> list[dict]:
    """Preview the first `limit` rows of `database`.`table` (1..100)."""
    db = _quote_ident(database)
    tbl = _quote_ident(table)
    if not isinstance(limit, int) or limit < 1 or limit > 100:
        raise ValueError("limit must be an integer between 1 and 100")
    return _run(f"SELECT * FROM {db}.{tbl} LIMIT {limit}")


@mcp.tool()
def execute_query(query: str) -> list[dict]:
    """Execute a HiveQL query and return results as a list of row dicts.

    When HIVE_READ_ONLY is true (the default), write DDL/DML is rejected.
    Results are capped at HIVE_QUERY_ROW_LIMIT rows.
    """
    cfg = _cfg()
    if cfg["read_only"] and not _is_read_only(query):
        raise ValueError(
            "Write query rejected: server is in read-only mode. "
            "Set HIVE_READ_ONLY=false to allow DDL/DML."
        )
    return _run(query, row_limit=cfg["row_limit"])


def main() -> None:
    """Console-script entry point invoked by `hive-mcp-server` / `uvx`."""
    mcp.run()


if __name__ == "__main__":
    main()
