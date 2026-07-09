# Cloudera Hive MCP Server

A standard [Model Context Protocol](https://modelcontextprotocol.io/) server that
exposes a Cloudera Data Warehouse **Virtual Warehouse** (Hive) to any MCP client
— Claude Desktop, Claude Code, the Claude Agent SDK, LangChain, LlamaIndex,
Cline, Continue, etc.

## Tools

| Tool               | Purpose                                                          |
| ------------------ | ---------------------------------------------------------------- |
| `list_databases`   | List every database in the Virtual Warehouse.                    |
| `list_tables`      | List tables in a given database.                                 |
| `describe_table`   | Return columns, types, and comments for a table.                 |
| `get_table_sample` | Preview the first N rows (1–100) of a table.                     |
| `execute_query`    | Run a HiveQL query. Read-only by default; row-capped for safety. |

## Prerequisites

- Python 3.10+
- Network access to your Cloudera Virtual Warehouse (typically `*.dw.cloudera.site:443`)
- A **workload user + password** with query privileges on the target VW

## Recommended install: `uvx` from Git (zero-setup for clients)

`uvx` is the Python analog of `npx`. It fetches the package, resolves its
dependencies into an isolated cache, and runs the entry point — no clone,
no venv, no `pip install` on the client machine.

**One-time on the client machine — install [`uv`](https://docs.astral.sh/uv/) (ships `uvx`):**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh    # macOS / Linux
# Windows:  powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Then any MCP client can launch this server with:

```bash
uvx --from git+https://github.com/mjain/hive-mcp-server hive-mcp-server
```

(replace the Git URL with your fork / internal mirror)

### Environment variables

The server needs Hive credentials in its environment. Every MCP client config
below sets them via an `env` block — no `.env` file needed on the client.

| Variable               | Default        | Description                                                    |
| ---------------------- | -------------- | -------------------------------------------------------------- |
| `HIVE_HOST`            | *(required)*   | Virtual Warehouse hostname                                     |
| `HIVE_PORT`            | `443`          | HTTPS port                                                     |
| `HIVE_HTTP_PATH`       | `/cliservice`  | HiveServer2 HTTP path                                          |
| `HIVE_USERNAME`        | *(required)*   | Cloudera workload user                                         |
| `HIVE_PASSWORD`        | *(required)*   | Cloudera workload password                                     |
| `HIVE_READ_ONLY`       | `true`         | If true, `execute_query` rejects DDL/DML                       |
| `HIVE_QUERY_ROW_LIMIT` | `1000`         | Max rows returned by `execute_query`                           |
| `MCP_TRANSPORT`        | `stdio`        | Transport passed to `mcp.run()`. Use `stdio` for MCP clients; set to `sse` when driving via the MCP Inspector. |

---

## Client setup

### Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS)
or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "hive": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/mjain/hive-mcp-server",
        "hive-mcp-server"
      ],
      "env": {
        "HIVE_HOST": "your-vw-host.dw.cloudera.site",
        "HIVE_USERNAME": "your-workload-user",
        "HIVE_PASSWORD": "your-workload-password",
        "HIVE_READ_ONLY": "true"
      }
    }
  }
}
```

Fully quit Claude Desktop (⌘Q) and reopen. The five Hive tools appear in the
tool tray.

### Claude Code CLI

```bash
claude mcp add hive \
  --env HIVE_HOST=your-vw-host.dw.cloudera.site \
  --env HIVE_USERNAME=your-workload-user \
  --env HIVE_PASSWORD=your-workload-password \
  -- uvx --from git+https://github.com/mjain/hive-mcp-server hive-mcp-server
```

Add `-s user` before `hive` to make it available in every project.

### Claude Agent SDK (Python)

```python
# pip install claude-agent-sdk
import asyncio
from claude_agent_sdk import query, ClaudeAgentOptions

async def main():
    options = ClaudeAgentOptions(
        mcp_servers={
            "hive": {
                "type": "stdio",
                "command": "uvx",
                "args": [
                    "--from",
                    "git+https://github.com/mjain/hive-mcp-server",
                    "hive-mcp-server",
                ],
                "env": {
                    "HIVE_HOST": "your-vw-host.dw.cloudera.site",
                    "HIVE_USERNAME": "your-workload-user",
                    "HIVE_PASSWORD": "your-workload-password",
                    "HIVE_READ_ONLY": "true",
                },
            }
        },
        allowed_tools=[
            "mcp__hive__list_databases",
            "mcp__hive__list_tables",
            "mcp__hive__describe_table",
            "mcp__hive__get_table_sample",
            "mcp__hive__execute_query",
        ],
    )
    async for msg in query(
        prompt="List all Hive databases, then describe the largest table in the first one.",
        options=options,
    ):
        print(msg)

asyncio.run(main())
```

The same `{command, args, env}` shape works for LangChain's MCP adapter,
LlamaIndex, Cline, Continue, Zed, and every other MCP client.

---

## Local development

Clone and install in editable mode when working on the server itself:

```bash
git clone <this repo>
cd hive-mcp-server-claude
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env    # fill in credentials
hive-mcp-server         # runs on stdio; Ctrl-C to stop
```

Smoke-test the connection:

```bash
python -c "from hive_mcp_server.tools.hive_tools import list_databases; print(list_databases())"
```

### Code layout

The server follows the same pattern as
[`cloudera/iceberg-mcp-server`](https://github.com/cloudera/iceberg-mcp-server):

```
src/hive_mcp_server/
├── __init__.py           # version + main/mcp re-exports
├── server.py             # thin MCP registration layer (@mcp.tool wrappers)
└── tools/
    ├── __init__.py
    └── hive_tools.py     # config, connection, SQL safety, tool logic
```

To add a new tool: implement it in `tools/hive_tools.py`, then add a
matching `@mcp.tool()` wrapper in `server.py` whose docstring becomes the
tool description exposed to the LLM.

### Transport

By default the server runs on `stdio`, which is what all MCP clients
(Claude Desktop, Claude Code, etc.) expect. To use the MCP Inspector web
UI instead:

```bash
MCP_TRANSPORT=sse hive-mcp-server
```

## Publishing your own fork

Push to any Git host — clients reference the URL:

```bash
git init && git add . && git commit -m "initial"
git remote add origin https://github.com/<you>/hive-mcp-server
git push -u origin main
```

Then everyone points their `uvx --from git+...` at your URL. To publish to
PyPI so clients can just say `uvx hive-mcp-server` (no `--from`):

```bash
pip install build twine
python -m build
twine upload dist/*
```

## Safety

- **`HIVE_READ_ONLY=true` (default)** — `execute_query` rejects
  `INSERT / UPDATE / DELETE / DROP / ALTER / TRUNCATE / CREATE / REPLACE / MERGE / GRANT / REVOKE / MSCK / LOAD / EXPORT / IMPORT`.
- **`HIVE_QUERY_ROW_LIMIT=1000`** — caps `execute_query` results so a
  `SELECT *` on a billion-row table doesn't blow up the agent's context.
- **Identifier validation** — `database` and `table` arguments must match
  `[A-Za-z_][A-Za-z0-9_]*`; anything else is rejected before reaching Hive.
- **No credentials in tool arguments** — the connection is configured
  entirely through environment variables; agents cannot see or override them.

## License

MIT.
