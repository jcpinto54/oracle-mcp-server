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

class OracleMCPServer:
    """Oracle Database MCP Server"""
    
    def __init__(self, config_path: str = "config.json"):
        """Initialize the Oracle MCP Server"""
        self.config = self._load_config(config_path)
        self.connection = None
        self.server = Server("oracle-sql-helper")
        self._setup_tools()
        
    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """Load configuration from JSON file"""
        try:
            with open(config_path, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            logger.error(f"Configuration file {config_path} not found")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in configuration file: {e}")
            raise
    
    def _setup_tools(self):
        """Setup MCP tools"""
        
        @self.server.list_tools()
        async def handle_list_tools() -> List[Tool]:
            """List available tools"""
            return [
                Tool(
                    name="execute_sql",
                    description="Execute SQL query against Oracle database",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "SQL query to execute"
                            },
                            "params": {
                                "type": "array",
                                "description": "Optional parameters for parameterized queries",
                                "items": {"type": "string"}
                            }
                        },
                        "required": ["query"]
                    }
                )
            ]
        
        @self.server.call_tool()
        async def handle_call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
            """Handle tool calls"""
            try:
                if name == "execute_sql":
                    return await self._execute_sql(arguments)
                else:
                    return [TextContent(type="text", text=f"Unknown tool: {name}")]
            except Exception as e:
                logger.error(f"Error in tool {name}: {e}")
                logger.error(traceback.format_exc())
                return [TextContent(type="text", text=f"Error executing {name}: {str(e)}")]
    
    async def _connect_database(self):
        """Connect to Oracle database"""
        if self.connection is not None:
            return
            
        if oracledb is None:
            raise ImportError("oracledb library not installed. Install with: pip install oracledb")
        
        try:
            db_config = self.config["database"]
            
            # Create connection string
            if db_config.get("service_name"):
                dsn = f"{db_config['host']}:{db_config['port']}/{db_config['service_name']}"
            else:
                dsn = f"{db_config['host']}:{db_config['port']}/{db_config['sid']}"
            
            self.connection = oracledb.connect(
                user=db_config["username"],
                password=db_config["password"],
                dsn=dsn
            )
            
            logger.info("Successfully connected to Oracle database")
            
        except Exception as e:
            logger.error(f"Failed to connect to Oracle database: {e}")
            raise
    
    async def _execute_sql(self, arguments: Dict[str, Any]) -> List[TextContent]:
        """Execute SQL query"""
        await self._connect_database()
        
        query = arguments["query"]
        params = arguments.get("params", [])
        
        try:
            cursor = self.connection.cursor()
            
            # Execute query
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            
            # Handle different query types
            if query.strip().upper().startswith(("SELECT", "WITH")):
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
                        for val in row:
                            if val is None:
                                formatted_row.append("NULL")
                            elif isinstance(val, (datetime,)):
                                formatted_row.append(val.strftime("%Y-%m-%d %H:%M:%S"))
                            else:
                                formatted_row.append(str(val))
                        result += " | ".join(formatted_row) + "\n"
                    
                    result += truncated_msg
                else:
                    result = "Query executed successfully. No rows returned."
                    
            else:
                # For INSERT, UPDATE, DELETE, etc.
                self.connection.commit()
                result = f"Query executed successfully. {cursor.rowcount} rows affected."
            
            cursor.close()
            return [TextContent(type="text", text=result)]
            
        except Exception as e:
            logger.error(f"Error executing SQL: {e}")
            return [TextContent(type="text", text=f"SQL Error: {str(e)}")]
    
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
        except Exception as e:
            logger.error(f"Error in server run: {e}")
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
    except Exception as e:
        logger.error(f"Server error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
