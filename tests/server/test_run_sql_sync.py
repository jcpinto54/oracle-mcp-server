"""
Tests for OracleMCPServer._run_sql_sync using fake connections and cursors.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional, Sequence
from unittest.mock import MagicMock

import pytest

from tests.conftest import minimal_server_config

from oracle_mcp_server.server import OracleMCPServer


class FakeCursor:
    """Minimal cursor stub for _run_sql_sync."""

    def __init__(
        self,
        description: Optional[Sequence],
        rows: Optional[List] = None,
        rowcount: int = 0,
        raise_on_execute: Optional[Exception] = None,
    ) -> None:
        self.description = description
        self._rows = rows or []
        self.rowcount = rowcount
        self.raise_on_execute = raise_on_execute
        self.last_query: Optional[str] = None
        self.last_params: Any = None
        self.closed = False

    def execute(self, query_str: str, params: Any = None) -> None:
        self.last_query = query_str
        self.last_params = params
        if self.raise_on_execute:
            raise self.raise_on_execute

    def fetchall(self) -> List:
        return list(self._rows)

    def close(self) -> None:
        self.closed = True


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor
        self.commit_called = False
        self.rollback_called = False

    def cursor(self) -> FakeCursor:
        return self._cursor

    def commit(self) -> None:
        self.commit_called = True

    def rollback(self) -> None:
        self.rollback_called = True


@pytest.fixture
def server_with_max_results(tmp_path: Path) -> OracleMCPServer:
    config_dict = minimal_server_config(max_results=2)
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config_dict), encoding="utf-8")
    return OracleMCPServer(str(path))


def test_run_sql_sync_select_truncates_rows(server_with_max_results: OracleMCPServer) -> None:
    rows = [(1,), (2,), (3,)]
    cursor = FakeCursor(description=[("N",)], rows=rows)
    connection = FakeConnection(cursor)
    result = server_with_max_results._run_sql_sync(
        connection, "SELECT n FROM t", [], "sql_read"
    )
    assert "truncated to 2 rows" in result[0].text
    assert connection.commit_called is True
    assert cursor.closed is True


def test_run_sql_sync_select_no_rows(server_with_max_results: OracleMCPServer) -> None:
    cursor = FakeCursor(description=[("N",)], rows=[])
    connection = FakeConnection(cursor)
    result = server_with_max_results._run_sql_sync(
        connection, "SELECT n FROM t WHERE 1=0", [], "sql_read"
    )
    assert "No rows returned" in result[0].text
    assert connection.commit_called is True


def test_run_sql_sync_formats_datetime(server_with_max_results: OracleMCPServer) -> None:
    sample_dt = datetime(2024, 6, 1, 15, 30, 45)
    cursor = FakeCursor(description=[("D",)], rows=[(sample_dt,)])
    connection = FakeConnection(cursor)
    result = server_with_max_results._run_sql_sync(
        connection, "SELECT d FROM t", [], "sql_read"
    )
    assert "2024-06-01 15:30:45" in result[0].text


def test_run_sql_sync_null_cell_renders_as_null(server_with_max_results: OracleMCPServer) -> None:
    cursor = FakeCursor(description=[("C",)], rows=[(None,)])
    connection = FakeConnection(cursor)
    result = server_with_max_results._run_sql_sync(
        connection, "SELECT c FROM t", [], "sql_read"
    )
    assert "NULL" in result[0].text


def test_run_sql_sync_passes_params_to_execute(server_with_max_results: OracleMCPServer) -> None:
    cursor = FakeCursor(description=None, rowcount=1)
    connection = FakeConnection(cursor)
    server_with_max_results._run_sql_sync(
        connection, "INSERT INTO t VALUES (:1)", ["x"], "sql_write"
    )
    assert cursor.last_query == "INSERT INTO t VALUES (:1)"
    assert cursor.last_params == ["x"]


def test_run_sql_sync_dml_commits_for_classified_tool(
    server_with_max_results: OracleMCPServer,
) -> None:
    cursor = FakeCursor(description=None, rowcount=4)
    connection = FakeConnection(cursor)
    result = server_with_max_results._run_sql_sync(
        connection, "UPDATE t SET a=1", [], "sql_write"
    )
    assert "4 rows affected" in result[0].text
    assert connection.commit_called is True


def test_run_sql_sync_sql_full_does_not_commit(
    server_with_max_results: OracleMCPServer,
) -> None:
    cursor = FakeCursor(description=None, rowcount=0)
    connection = FakeConnection(cursor)
    server_with_max_results._run_sql_sync(
        connection, "COMMIT", [], "sql_full"
    )
    assert connection.commit_called is False


def test_run_sql_sync_failure_rolls_back(server_with_max_results: OracleMCPServer) -> None:
    cursor = FakeCursor(
        description=[("N",)],
        rows=[],
        raise_on_execute=RuntimeError("ORA-00001"),
    )
    connection = FakeConnection(cursor)
    with pytest.raises(RuntimeError, match="ORA-00001"):
        server_with_max_results._run_sql_sync(
            connection, "SELECT 1", [], "sql_read"
        )
    assert connection.rollback_called is True
    assert connection.commit_called is False


def test_run_sql_sync_uses_default_max_results_from_config(tmp_path: Path) -> None:
    """When mcp.max_results is omitted, _run_sql_sync uses default 1000 (no truncation for small sets)."""
    config_dict = minimal_server_config()
    del config_dict["mcp"]["max_results"]
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config_dict), encoding="utf-8")
    server = OracleMCPServer(str(path))
    rows = [(MagicMock(),)]
    cursor = FakeCursor(description=[("X",)], rows=rows)
    connection = FakeConnection(cursor)
    result = server._run_sql_sync(connection, "SELECT x FROM t", [], "sql_read")
    assert "Found 1 rows" in result[0].text
    assert "truncated" not in result[0].text.lower()
