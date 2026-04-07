"""
Oracle Database MCP server: tool registration, connections, and SQL execution.
"""

import json
import logging
import traceback
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Dict, List

from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

try:
    import oracledb
except ImportError:
    oracledb = None

from sql_tier_policy import (
    _classify_minimum_sql_tier,
    _invoked_sql_tier,
    _non_empty_statement_count,
    _tenant_cap_error_message,
    _tier_check_error_message,
)
from tenant_config import SqlTier, _build_dsn, _parse_tenants

logger = logging.getLogger("oracle-mcp-server")

_SQL_PARAMETERIZATION_HINT = (
    "SQL injection risk: Anything interpolated or concatenated into this string (chat text, user "
    "input, documents, tool output) can change statement meaning and exfiltrate or destroy data, "
    "escalate privileges, or bypass tier limits inside one \"query\". Always pass variable data via "
    "binds: use :1, :2, … in the SQL text and the same-ordered values in params (JSON string "
    "array). Omit params or use [] only when there are no bind placeholders."
)

_SQL_TOOL_INPUT_PROPERTIES = {
    "tenant_id": {
        "type": "string",
        "description": "Tenant identifier from the configuration (see list_tenants)",
    },
    "query": {
        "type": "string",
        "description": (
            "Single SQL statement for this tenant (unless using sql_full for scripts). "
            + _SQL_PARAMETERIZATION_HINT
        ),
    },
    "params": {
        "type": "array",
        "description": (
            "Bind values for parameterized SQL—primary defense against SQL injection together with "
            "placeholders in query. For :1, :2, … in query, pass params[0], params[1], … as strings. "
            "Omit or [] if query has no binds. Never smuggle variable text by building query strings."
        ),
        "items": {"type": "string"},
    },
}

_SQL_TOOLS_SHARED_INPUT_SCHEMA = {
    "type": "object",
    "properties": _SQL_TOOL_INPUT_PROPERTIES,
    "required": ["tenant_id", "query"],
}

_SQL_TIER_DESCRIPTION_PREAMBLE = (
    "Four tools are nested by privilege: sql_read, then sql_write, then sql_ddl, then sql_full "
    "(each includes everything the lower ones allow). Prefer the least powerful tool that fits. "
    "Use list_tenants for tenant_id. "
    "SQL injection is a serious risk: never embed raw user/chat/LLM-derived text inside query; "
    "use :1, :2, binds and params instead. Tier limits reduce blast radius but do not fix injection."
)


class OracleMCPServer:
    """Oracle Database MCP Server"""

    def __init__(self, config_path: str = "config.json"):
        """Initialize the Oracle MCP Server"""
        self.config = self._load_config(config_path)
        self.tenant_configs = _parse_tenants(self.config)
        self._connections: Dict[str, Any] = {}
        self.server = Server("oracle-sql-helper")
        self._setup_tools()

    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """Load configuration from JSON file"""
        try:
            with open(config_path, 'r', encoding="utf-8") as config_file_handle:
                return json.load(config_file_handle)
        except FileNotFoundError:
            logger.error("Configuration file %s not found", config_path)
            raise
        except json.JSONDecodeError as decode_error:
            logger.error("Invalid JSON in configuration file: %s", decode_error)
            raise

    def _setup_tools(self):
        """Setup MCP tools"""

        @self.server.list_tools()
        async def handle_list_tools() -> List[Tool]:
            """List available tools"""
            return [
                Tool(
                    name="list_tenants",
                    description=(
                        "List configured Oracle database tenants (tenant_id, host, port, "
                        "and service_name or sid). Call this before any sql_* tool to pick "
                        "tenant_id. Passwords are never returned."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {},
                    },
                ),
                Tool(
                    name="sql_read",
                    description=(
                        f"{_SQL_TIER_DESCRIPTION_PREAMBLE} "
                        "sql_read: single SQL statement, read-oriented only (SELECT and read-safe WITH). "
                        "No DML, no DDL, no EXPLAIN PLAN (use sql_write), no PL/SQL, no COMMIT/ROLLBACK, "
                        "no multi-statement scripts. Injection can still leak arbitrary readable data—use "
                        "binds for any variable predicates or literals."
                    ),
                    inputSchema=dict(_SQL_TOOLS_SHARED_INPUT_SCHEMA),
                ),
                Tool(
                    name="sql_write",
                    description=(
                        f"{_SQL_TIER_DESCRIPTION_PREAMBLE} "
                        "sql_write: everything sql_read allows, plus row-changing DML (INSERT, UPDATE, DELETE, "
                        "MERGE), EXPLAIN PLAN, SELECT FOR UPDATE, LOCK TABLE. Still one statement only; "
                        "no DDL (CREATE/ALTER/DROP/... use sql_ddl), no GRANT/REVOKE, no PL/SQL blocks, "
                        "no transaction commands — use sql_full for those. Server commits after success. "
                        "Injection here can alter or delete data—use binds for all untrusted values."
                    ),
                    inputSchema=dict(_SQL_TOOLS_SHARED_INPUT_SCHEMA),
                ),
                Tool(
                    name="sql_ddl",
                    description=(
                        f"{_SQL_TIER_DESCRIPTION_PREAMBLE} "
                        "sql_ddl: everything sql_write allows, plus DDL-style changes (CREATE, ALTER on "
                        "schema objects, DROP, TRUNCATE, RENAME, COMMENT ON). One statement; server commits "
                        "after success. For GRANT/REVOKE, PL/SQL, session ALTER SESSION/SYSTEM, scripts, "
                        "or COMMIT/ROLLBACK use sql_full. "
                        "Injection can drop objects or redefine schema—use binds; avoid string-building DDL."
                    ),
                    inputSchema=dict(_SQL_TOOLS_SHARED_INPUT_SCHEMA),
                ),
                Tool(
                    name="sql_full",
                    description=(
                        f"{_SQL_TIER_DESCRIPTION_PREAMBLE} "
                        "sql_full: break-glass — no statement classification; any SQL/PL/SQL Oracle accepts "
                        "(including multi-statement scripts, COMMIT/ROLLBACK/SAVEPOINT, GRANT, anonymous "
                        "blocks). Server does not auto-commit; tenant sql_max_tier may still reject work. "
                        "Highest injection impact: only use with extreme care; prefer binds everywhere."
                    ),
                    inputSchema=dict(_SQL_TOOLS_SHARED_INPUT_SCHEMA),
                ),
            ]

        @self.server.call_tool()
        async def handle_call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
            """Handle tool calls"""
            try:
                if name == "list_tenants":
                    return await self._list_tenants()
                if name in ("sql_read", "sql_write", "sql_ddl", "sql_full"):
                    return await self._execute_tiered_sql(name, arguments or {})
                return [TextContent(type="text", text=f"Unknown tool: {name}")]
            except Exception as tool_error:
                logger.error("Error in tool %s: %s", name, tool_error)
                logger.error(traceback.format_exc())
                return [TextContent(type="text", text=f"Error executing {name}: {str(tool_error)}")]

    async def _list_tenants(self) -> List[TextContent]:
        """Return configured tenants without credentials."""
        listing: List[Dict[str, Any]] = []
        tier_label = {SqlTier.READ: "read", SqlTier.WRITE: "write", SqlTier.DDL: "ddl", SqlTier.FULL: "full"}
        for tenant_id in sorted(self.tenant_configs.keys()):
            tenant_cfg = self.tenant_configs[tenant_id]
            entry: Dict[str, Any] = {
                "tenant_id": tenant_id,
                "host": tenant_cfg["host"],
                "port": tenant_cfg["port"],
                "sql_max_tier": tier_label[tenant_cfg["sql_max_tier"]],
            }
            if tenant_cfg.get("service_name"):
                entry["service_name"] = tenant_cfg["service_name"]
            else:
                entry["sid"] = tenant_cfg["sid"]
            listing.append(entry)
        payload = {"tenants": listing}
        return [TextContent(type="text", text=json.dumps(payload, indent=2))]

    async def _get_connection(self, tenant_id: str) -> Any:
        """Return an Oracle connection for the tenant, opening it if needed."""
        if oracledb is None:
            raise ImportError("oracledb library not installed. Install with: pip install oracledb")

        stable_id = (tenant_id or "").strip()
        if stable_id not in self.tenant_configs:
            raise ValueError(
                f'Unknown tenant_id "{tenant_id}". Use list_tenants to see valid ids.'
            )

        if stable_id not in self._connections:
            tenant_cfg = self.tenant_configs[stable_id]
            dsn = _build_dsn(tenant_cfg)
            try:
                self._connections[stable_id] = oracledb.connect(
                    user=tenant_cfg["username"],
                    password=tenant_cfg["password"],
                    dsn=dsn,
                )
                logger.info("Connected to Oracle for tenant %s", stable_id)
            except Exception as connect_error:
                logger.error("Failed to connect for tenant %s: %s", stable_id, connect_error)
                raise

        return self._connections[stable_id]

    async def _execute_tiered_sql(self, tool_name: str, arguments: Dict[str, Any]) -> List[TextContent]:
        """Validate tier, execute SQL, apply commit/rollback policy."""
        tenant_id = arguments.get("tenant_id")
        if tenant_id is None or not str(tenant_id).strip():
            return [TextContent(
                type="text",
                text='Error: "tenant_id" is required. Use list_tenants for valid tenant ids.',
            )]

        stable_tenant_id = str(tenant_id).strip()

        try:
            connection = await self._get_connection(stable_tenant_id)
        except ValueError as unknown_tenant:
            return [TextContent(type="text", text=str(unknown_tenant))]
        except Exception as connect_error:
            return [TextContent(type="text", text=f"Connection error: {connect_error}")]

        tenant_cfg = self.tenant_configs[stable_tenant_id]
        query = arguments.get("query")
        if query is None or not str(query).strip():
            return [TextContent(type="text", text='Error: "query" must be a non-empty string.')]

        query_str = str(query)
        params = arguments.get("params", [])
        invoked = _invoked_sql_tier(tool_name)
        tenant_cap = tenant_cfg["sql_max_tier"]

        if tool_name in ("sql_read", "sql_write", "sql_ddl"):
            stmt_count = _non_empty_statement_count(query_str)
            if stmt_count != 1:
                return [TextContent(
                    type="text",
                    text=(
                        "Error: sql_read, sql_write, and sql_ddl accept exactly one SQL statement. "
                        f"Found {stmt_count} non-empty segment(s) after splitting on top-level ';'."
                    ),
                )]

        required = _classify_minimum_sql_tier(query_str)
        if required > tenant_cap:
            return [TextContent(type="text", text=_tenant_cap_error_message(required, tenant_cap))]

        if invoked != SqlTier.FULL and invoked < required:
            return [TextContent(type="text", text=_tier_check_error_message(invoked, required, tool_name))]

        try:
            return self._run_sql_sync(connection, query_str, params, tool_name)
        except Exception as sql_error:
            logger.error("Error executing SQL: %s", sql_error)
            return [TextContent(type="text", text=f"SQL Error: {str(sql_error)}")]

    def _run_sql_sync(self, connection: Any, query_str: str, params: Any, tool_name: str) -> List[TextContent]:
        """Run SQL on the connection (sync, for thread offload)."""
        cursor = connection.cursor()
        classified = tool_name in ("sql_read", "sql_write", "sql_ddl")
        try:
            if params:
                cursor.execute(query_str, params)
            else:
                cursor.execute(query_str)

            result_text: str
            if cursor.description is not None:
                columns = [desc[0] for desc in cursor.description]
                rows = cursor.fetchall()

                max_results = self.config["mcp"].get("max_results", 1000)
                if len(rows) > max_results:
                    rows = rows[:max_results]
                    truncated_msg = f"\n\n(Results truncated to {max_results} rows)"
                else:
                    truncated_msg = ""

                if rows:
                    result_text = f"Query executed successfully. Found {len(rows)} rows.\n\n"
                    result_text += " | ".join(columns) + "\n"
                    result_text += "-" * (len(" | ".join(columns))) + "\n"

                    for row in rows:
                        formatted_row = []
                        for cell in row:
                            if cell is None:
                                formatted_row.append("NULL")
                            elif isinstance(cell, datetime):
                                formatted_row.append(cell.strftime("%Y-%m-%d %H:%M:%S"))
                            else:
                                formatted_row.append(str(cell))
                        result_text += " | ".join(formatted_row) + "\n"

                    result_text += truncated_msg
                else:
                    result_text = "Query executed successfully. No rows returned."
            else:
                result_text = f"Query executed successfully. {cursor.rowcount} rows affected."

            if classified:
                connection.commit()

            return [TextContent(type="text", text=result_text)]
        except Exception:
            connection.rollback()
            raise
        finally:
            cursor.close()

    async def run(self):
        """Run the MCP server"""
        logger.info("Starting Oracle MCP Server")

        try:
            async with stdio_server() as (read_stream, write_stream):
                logger.info("stdio server initialized successfully")

                notification_options = SimpleNamespace()
                notification_options.tools_changed = False
                notification_options.resources_changed = False
                notification_options.prompts_changed = False

                await self.server.run(
                    read_stream,
                    write_stream,
                    InitializationOptions(
                        server_name=self.config["mcp"]["server_name"],
                        server_version=self.config["mcp"]["version"],
                        capabilities=self.server.get_capabilities(
                            notification_options=notification_options,
                            experimental_capabilities={}
                        )
                    )
                )
        except Exception as run_error:
            logger.error("Error in server run: %s", run_error)
            logger.error(traceback.format_exc())
            raise
