#!/usr/bin/env python3
"""
Oracle Database MCP Server
A Model Context Protocol server for executing SQL queries against Oracle Database
"""

import asyncio
import json
import logging
import sys
from typing import Any, Dict, List
import traceback
from datetime import datetime

# MCP imports
from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
from mcp.types import (
    Tool,
    TextContent,
)
from types import SimpleNamespace

# Oracle database imports
try:
    import oracledb
except ImportError:
    oracledb = None

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('mcp_server.log'),
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("oracle-mcp-server")


def _normalize_tenant_config(
    tenant_id: str,
    raw_config: Any,
) -> Dict[str, Any]:
    """Validate and normalize a single tenant connection block."""
    if not isinstance(raw_config, dict):
        raise ValueError(
            f'Tenant "{tenant_id}": connection must be a JSON object'
        )

    required_string_keys = ("host", "username", "password")
    for key in required_string_keys:
        if key not in raw_config:
            raise ValueError(f'Tenant "{tenant_id}": missing required field "{key}"')
        value = raw_config[key]
        if value is None or (isinstance(value, str) and not value.strip()):
            raise ValueError(
                f'Tenant "{tenant_id}": "{key}" must be a non-empty string'
            )
        if not isinstance(value, str):
            raise ValueError(f'Tenant "{tenant_id}": "{key}" must be a string')

    if "port" not in raw_config:
        raise ValueError(f'Tenant "{tenant_id}": missing required field "port"')
    try:
        port = int(raw_config["port"])
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f'Tenant "{tenant_id}": "port" must be an integer'
        ) from exc
    if port < 1 or port > 65535:
        raise ValueError(f'Tenant "{tenant_id}": "port" must be between 1 and 65535')

    service_name = raw_config.get("service_name")
    sid = raw_config.get("sid")

    if service_name is not None and not isinstance(service_name, str):
        raise ValueError(f'Tenant "{tenant_id}": "service_name" must be a string or null')
    if sid is not None and not isinstance(sid, str):
        raise ValueError(f'Tenant "{tenant_id}": "sid" must be a string or null')

    service_name_clean = service_name.strip() if service_name else ""
    sid_clean = sid.strip() if sid else ""

    if service_name_clean and sid_clean:
        raise ValueError(
            f'Tenant "{tenant_id}": set exactly one of "service_name" or "sid", not both'
        )
    if not service_name_clean and not sid_clean:
        raise ValueError(
            f'Tenant "{tenant_id}": must set either "service_name" or "sid" (non-empty)'
        )

    normalized: Dict[str, Any] = {
        "host": raw_config["host"].strip(),
        "port": port,
        "username": raw_config["username"].strip(),
        "password": raw_config["password"],
    }
    if service_name_clean:
        normalized["service_name"] = service_name_clean
        normalized["sid"] = None
    else:
        normalized["service_name"] = None
        normalized["sid"] = sid_clean

    return normalized


def _parse_tenants(config: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Parse and validate the top-level tenants map."""
    if "tenants" not in config:
        raise ValueError('Configuration must contain a "tenants" object')
    tenants_raw = config["tenants"]
    if not isinstance(tenants_raw, dict) or len(tenants_raw) == 0:
        raise ValueError('"tenants" must be a non-empty object')

    tenant_configs: Dict[str, Dict[str, Any]] = {}
    for tenant_id, raw in tenants_raw.items():
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("Each tenant key must be a non-empty string")
        stable_id = tenant_id.strip()
        if stable_id in tenant_configs:
            raise ValueError(f'Duplicate tenant id after trimming: "{stable_id}"')
        tenant_configs[stable_id] = _normalize_tenant_config(stable_id, raw)

    return tenant_configs


def _build_dsn(tenant_config: Dict[str, Any]) -> str:
    host = tenant_config["host"]
    port = tenant_config["port"]
    if tenant_config.get("service_name"):
        return f"{host}:{port}/{tenant_config['service_name']}"
    return f"{host}:{port}/{tenant_config['sid']}"


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
                        "and service_name or sid). Call this before execute_sql to choose "
                        "a valid tenant_id. Passwords are never returned."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {},
                    },
                ),
                Tool(
                    name="execute_sql",
                    description=(
                        "Execute SQL query against the Oracle database for a specific tenant. "
                        "Use list_tenants to discover tenant_id values."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "tenant_id": {
                                "type": "string",
                                "description": (
                                    "Tenant identifier from the configuration (see list_tenants)"
                                ),
                            },
                            "query": {
                                "type": "string",
                                "description": "SQL query to execute",
                            },
                            "params": {
                                "type": "array",
                                "description": "Optional parameters for parameterized queries",
                                "items": {"type": "string"},
                            },
                        },
                        "required": ["tenant_id", "query"],
                    },
                ),
            ]

        @self.server.call_tool()
        async def handle_call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
            """Handle tool calls"""
            try:
                if name == "list_tenants":
                    return await self._list_tenants()
                if name == "execute_sql":
                    return await self._execute_sql(arguments)
                return [TextContent(type="text", text=f"Unknown tool: {name}")]
            except Exception as tool_error:
                logger.error("Error in tool %s: %s", name, tool_error)
                logger.error(traceback.format_exc())
                return [TextContent(type="text", text=f"Error executing {name}: {str(tool_error)}")]

    async def _list_tenants(self) -> List[TextContent]:
        """Return configured tenants without credentials."""
        listing: List[Dict[str, Any]] = []
        for tenant_id in sorted(self.tenant_configs.keys()):
            tenant_cfg = self.tenant_configs[tenant_id]
            entry: Dict[str, Any] = {
                "tenant_id": tenant_id,
                "host": tenant_cfg["host"],
                "port": tenant_cfg["port"],
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

    async def _execute_sql(self, arguments: Dict[str, Any]) -> List[TextContent]:
        """Execute SQL query"""
        tenant_id = arguments.get("tenant_id")
        if tenant_id is None or not str(tenant_id).strip():
            return [TextContent(
                type="text",
                text='Error: "tenant_id" is required. Use list_tenants for valid tenant ids.',
            )]

        try:
            connection = await self._get_connection(str(tenant_id))
        except ValueError as unknown_tenant:
            return [TextContent(type="text", text=str(unknown_tenant))]
        except Exception as connect_error:
            return [TextContent(type="text", text=f"Connection error: {connect_error}")]

        query = arguments["query"]
        params = arguments.get("params", [])

        try:
            cursor = connection.cursor()

            # Execute query
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)

            # Handle different query types
            stripped = query.strip()
            if stripped.upper().startswith(("SELECT", "WITH")):
                # Fetch results for SELECT queries
                columns = [desc[0] for desc in cursor.description]
                rows = cursor.fetchall()

                # Limit results
                max_results = self.config["mcp"].get("max_results", 1000)
                if len(rows) > max_results:
                    rows = rows[:max_results]
                    truncated_msg = f"\n\n(Results truncated to {max_results} rows)"
                else:
                    truncated_msg = ""

                # Format results
                if rows:
                    # Create table format
                    result = f"Query executed successfully. Found {len(rows)} rows.\n\n"
                    result += " | ".join(columns) + "\n"
                    result += "-" * (len(" | ".join(columns))) + "\n"

                    for row in rows:
                        formatted_row = []
                        for cell in row:
                            if cell is None:
                                formatted_row.append("NULL")
                            elif isinstance(cell, datetime):
                                formatted_row.append(cell.strftime("%Y-%m-%d %H:%M:%S"))
                            else:
                                formatted_row.append(str(cell))
                        result += " | ".join(formatted_row) + "\n"

                    result += truncated_msg
                else:
                    result = "Query executed successfully. No rows returned."

            else:
                # For INSERT, UPDATE, DELETE, etc.
                connection.commit()
                result = f"Query executed successfully. {cursor.rowcount} rows affected."

            cursor.close()
            return [TextContent(type="text", text=result)]

        except Exception as sql_error:
            logger.error("Error executing SQL: %s", sql_error)
            return [TextContent(type="text", text=f"SQL Error: {str(sql_error)}")]

    async def run(self):
        """Run the MCP server"""
        logger.info("Starting Oracle MCP Server")

        try:
            # Initialize server
            async with stdio_server() as (read_stream, write_stream):
                logger.info("stdio server initialized successfully")

                # Create empty notification options
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


def main():
    """Main entry point"""
    if len(sys.argv) > 1:
        config_path = sys.argv[1]
    else:
        config_path = "config.json"

    try:
        server = OracleMCPServer(config_path)
        asyncio.run(server.run())
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as main_error:
        logger.error("Server error: %s", main_error)
        sys.exit(1)


if __name__ == "__main__":
    main()
