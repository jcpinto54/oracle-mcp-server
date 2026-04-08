#!/usr/bin/env python3
"""
Oracle Database MCP Server entry point.

After ``pip install -e .`` or installing from PyPI / ``uvx``:

- Pass the path to ``config.json`` as the first argument, or
- Set the ``ORACLE_MCP_CONFIG`` environment variable to that path.

Development shortcut: ``python -m oracle_mcp_server`` with the same rules.
"""

import asyncio
import logging
import os
import sys


def resolve_config_path():
    """Config file path from CLI (first arg) or ORACLE_MCP_CONFIG; else exit with usage."""
    if len(sys.argv) > 1:
        return sys.argv[1]

    env_config_path = os.environ.get("ORACLE_MCP_CONFIG")
    if env_config_path:
        return env_config_path

    program_name = os.path.basename(sys.argv[0]) if sys.argv else "oracle-mcp-server"
    usage_message = (
        f"Usage: {program_name} <path/to/config.json>\n"
        "Or set ORACLE_MCP_CONFIG to the config file path.\n"
    )
    sys.stderr.write(usage_message)
    sys.exit(2)


def main():
    """Main entry point"""
    config_path = resolve_config_path()

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('mcp_server.log'),
            logging.StreamHandler(sys.stderr)
        ]
    )
    logger = logging.getLogger("oracle-mcp-server")

    from oracle_mcp_server.server import OracleMCPServer  # noqa: E402 — logging configured first

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
