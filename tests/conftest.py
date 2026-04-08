"""
Shared pytest fixtures for oracle_mcp_server tests.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import MagicMock

import pytest


def minimal_server_config(
    max_results: int = 100,
    tenants: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Build a minimal valid config dict for OracleMCPServer."""
    if tenants is None:
        tenants = {
            "tenant_a": {
                "host": "oracle.example.com",
                "port": 1521,
                "username": "app_user",
                "password": "secret",
                "service_name": "ORCL",
                "sid": None,
                "sql_max_tier": "full",
            },
        }
    return {
        "tenants": tenants,
        "mcp": {
            "server_name": "test-server",
            "version": "0.0.1",
            "max_results": max_results,
        },
    }


@pytest.fixture
def temp_config_path(tmp_path: Path) -> Path:
    """Default minimal config written to tmp_path/config.json."""
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(minimal_server_config()),
        encoding="utf-8",
    )
    return config_path


@pytest.fixture
def mock_oracle_connection() -> MagicMock:
    """Connection mock with cursor() returning a MagicMock cursor."""
    connection_mock = MagicMock()
    cursor_mock = MagicMock()
    connection_mock.cursor.return_value = cursor_mock
    return connection_mock

