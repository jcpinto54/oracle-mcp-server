"""
Mocked tests for tier enforcement and _execute_tiered_sql guardrails.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from mcp.types import CallToolRequest, CallToolRequestParams

from tests.conftest import minimal_server_config

from oracle_mcp_server.server import OracleMCPServer


def write_config(
    tmp_path: Path, tenant_overrides: Optional[Dict[str, Dict[str, Any]]] = None
) -> Path:
    base = minimal_server_config()
    if tenant_overrides:
        base["tenants"] = tenant_overrides
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(base), encoding="utf-8")
    return config_path


@pytest.fixture
def tenant_full() -> Dict[str, Any]:
    return {
        "host": "h",
        "port": 1521,
        "username": "u",
        "password": "p",
        "service_name": "SVC",
        "sid": None,
        "sql_max_tier": "full",
    }


@pytest.fixture
def tenant_read_cap() -> Dict[str, Any]:
    block = {
        "host": "h",
        "port": 1521,
        "username": "u",
        "password": "p",
        "service_name": "SVC",
        "sid": None,
        "sql_max_tier": "read",
    }
    return block


@pytest.mark.asyncio
class TestExecuteTieredSqlValidation:
    async def test_rejects_missing_tenant_id(self, tmp_path: Path, tenant_full: Dict[str, Any]) -> None:
        path = write_config(tmp_path, {"t1": tenant_full})
        server = OracleMCPServer(str(path))
        result = await server._execute_tiered_sql("sql_read", {"query": "SELECT 1"})
        assert len(result) == 1
        assert "tenant_id" in result[0].text

    async def test_rejects_empty_tenant_id(self, tmp_path: Path, tenant_full: Dict[str, Any]) -> None:
        path = write_config(tmp_path, {"t1": tenant_full})
        server = OracleMCPServer(str(path))
        result = await server._execute_tiered_sql(
            "sql_read", {"tenant_id": "  ", "query": "SELECT 1"}
        )
        assert "tenant_id" in result[0].text

    async def test_unknown_tenant_message(self, tmp_path: Path, tenant_full: Dict[str, Any]) -> None:
        path = write_config(tmp_path, {"t1": tenant_full})
        server = OracleMCPServer(str(path))
        result = await server._execute_tiered_sql(
            "sql_read", {"tenant_id": "missing", "query": "SELECT 1"}
        )
        assert "Unknown tenant_id" in result[0].text

    async def test_connection_error_surfaces_as_text(self, tmp_path: Path, tenant_full: Dict[str, Any]) -> None:
        path = write_config(tmp_path, {"t1": tenant_full})
        server = OracleMCPServer(str(path))

        async def boom(_tenant: str) -> None:
            raise RuntimeError("network down")

        server._get_connection = boom  # type: ignore[method-assign]
        result = await server._execute_tiered_sql(
            "sql_read", {"tenant_id": "t1", "query": "SELECT 1 FROM dual"}
        )
        assert result[0].text.startswith("Connection error:")
        assert "network down" in result[0].text

    async def test_rejects_empty_query(self, tmp_path: Path, tenant_full: Dict[str, Any]) -> None:
        path = write_config(tmp_path, {"t1": tenant_full})
        server = OracleMCPServer(str(path))
        server._get_connection = AsyncMock(return_value=MagicMock())  # type: ignore[method-assign]
        result = await server._execute_tiered_sql(
            "sql_read", {"tenant_id": "t1", "query": "  "}
        )
        assert "query" in result[0].text

    async def test_classified_tools_reject_multi_statement(
        self, tmp_path: Path, tenant_full: Dict[str, Any]
    ) -> None:
        path = write_config(tmp_path, {"t1": tenant_full})
        server = OracleMCPServer(str(path))
        server._get_connection = AsyncMock(return_value=MagicMock())  # type: ignore[method-assign]
        result = await server._execute_tiered_sql(
            "sql_read", {"tenant_id": "t1", "query": "SELECT 1; SELECT 2"}
        )
        assert "exactly one SQL statement" in result[0].text

    async def test_tenant_cap_blocks_write(
        self, tmp_path: Path, tenant_read_cap: Dict[str, Any]
    ) -> None:
        path = write_config(tmp_path, {"t1": tenant_read_cap})
        server = OracleMCPServer(str(path))
        server._get_connection = AsyncMock(return_value=MagicMock())  # type: ignore[method-assign]
        result = await server._execute_tiered_sql(
            "sql_full",
            {"tenant_id": "t1", "query": "INSERT INTO x VALUES (1)"},
        )
        assert "sql_max_tier cap" in result[0].text

    async def test_tool_tier_too_low(
        self, tmp_path: Path, tenant_full: Dict[str, Any]
    ) -> None:
        path = write_config(tmp_path, {"t1": tenant_full})
        server = OracleMCPServer(str(path))
        server._get_connection = AsyncMock(return_value=MagicMock())  # type: ignore[method-assign]
        result = await server._execute_tiered_sql(
            "sql_read", {"tenant_id": "t1", "query": "INSERT INTO x VALUES (1)"},
        )
        assert "not sufficient" in result[0].text

    async def test_sql_full_allows_multiple_statements(
        self, tmp_path: Path, tenant_full: Dict[str, Any]
    ) -> None:
        path = write_config(tmp_path, {"t1": tenant_full})
        server = OracleMCPServer(str(path))
        fake_connection = MagicMock()
        server._get_connection = AsyncMock(return_value=fake_connection)  # type: ignore[method-assign]

        def fake_run_sql(
            connection: Any, query_str: str, params: Any, tool_name: str
        ) -> Any:
            assert ";" in query_str
            from mcp.types import TextContent

            return [TextContent(type="text", text="ok")]

        server._run_sql_sync = fake_run_sql  # type: ignore[method-assign]
        result = await server._execute_tiered_sql(
            "sql_full",
            {"tenant_id": "t1", "query": "SELECT 1; SELECT 2"},
        )
        assert result[0].text == "ok"

    async def test_sql_error_returns_text(self, tmp_path: Path, tenant_full: Dict[str, Any]) -> None:
        path = write_config(tmp_path, {"t1": tenant_full})
        server = OracleMCPServer(str(path))
        server._get_connection = AsyncMock(return_value=MagicMock())  # type: ignore[method-assign]

        def boom(_c: Any, _q: str, _p: Any, _t: str) -> None:
            raise Exception("ORA-00942")

        server._run_sql_sync = boom  # type: ignore[method-assign]
        result = await server._execute_tiered_sql(
            "sql_read", {"tenant_id": "t1", "query": "SELECT 1 FROM dual"}
        )
        assert result[0].text.startswith("SQL Error:")


@pytest.mark.asyncio
class TestCallToolDispatch:
    async def test_unknown_tool_returns_message(
        self, tmp_path: Path, tenant_full: Dict[str, Any]
    ) -> None:
        path = write_config(tmp_path, {"t1": tenant_full})
        server = OracleMCPServer(str(path))
        handler = server.server.request_handlers[CallToolRequest]
        request = CallToolRequest(
            params=CallToolRequestParams(name="not_a_registered_tool", arguments={})
        )
        result = await handler(request)
        tool_result = result.root
        assert tool_result.content[0].text.startswith("Unknown tool:")
