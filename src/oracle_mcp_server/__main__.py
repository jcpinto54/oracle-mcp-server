#!/usr/bin/env python3
"""
Oracle Database MCP Server entry point.

Run from the repository root after `pip install -e .`:
    python -m oracle_mcp_server
"""

import asyncio
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('mcp_server.log'),
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("oracle-mcp-server")

from oracle_mcp_server.server import OracleMCPServer  # noqa: E402 — logging must be configured first


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
