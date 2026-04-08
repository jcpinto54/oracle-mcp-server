"""
Unit tests for heuristic SQL tier classification and statement handling.
"""

import pytest

from oracle_mcp_server.sql_tier_policy import (
    _classify_minimum_sql_tier,
    _invoked_sql_tier,
    _non_empty_statement_count,
    _split_top_level_statement_segments,
    _strip_leading_sql_comments_and_whitespace,
    _tenant_cap_error_message,
    _tier_check_error_message,
)
from oracle_mcp_server.tenant_config import SqlTier


class TestStripLeadingComments:
    def test_strips_line_comment(self) -> None:
        assert _strip_leading_sql_comments_and_whitespace("-- hi\nSELECT 1") == "SELECT 1"

    def test_strips_block_comment(self) -> None:
        assert (
            _strip_leading_sql_comments_and_whitespace("/* c */ SELECT 1")
            == "SELECT 1"
        )

    def test_unclosed_block_comment_returns_empty(self) -> None:
        assert _strip_leading_sql_comments_and_whitespace("/* no end") == ""


class TestSplitTopLevelSegments:
    def test_splits_on_semicolon_outside_quotes(self) -> None:
        segments = _split_top_level_statement_segments("SELECT 1; SELECT 2")
        assert segments == ["SELECT 1", " SELECT 2"]

    def test_sem_in_single_quoted_literal_is_not_split(self) -> None:
        segments = _split_top_level_statement_segments("SELECT ';' FROM dual")
        assert len(segments) == 1
        assert segments[0] == "SELECT ';' FROM dual"

    def test_doubled_quote_escape_inside_string(self) -> None:
        segments = _split_top_level_statement_segments(
            "SELECT '''' FROM dual; SELECT 2"
        )
        assert len(segments) == 2


class TestNonEmptyStatementCount:
    def test_empty_string_is_zero(self) -> None:
        assert _non_empty_statement_count("") == 0

    def test_whitespace_only_is_zero(self) -> None:
        assert _non_empty_statement_count("  \n\t  ") == 0

    def test_single_statement_is_one(self) -> None:
        assert _non_empty_statement_count("SELECT 1 FROM dual") == 1

    def test_two_statements_is_two(self) -> None:
        assert _non_empty_statement_count("SELECT 1; SELECT 2") == 2

    def test_begin_always_counts_as_one_segment(self) -> None:
        assert _non_empty_statement_count("BEGIN NULL; END;") == 1


class TestClassifyMinimumSqlTier:
    def test_empty_query_is_read(self) -> None:
        assert _classify_minimum_sql_tier("") == SqlTier.READ

    def test_select_is_read(self) -> None:
        assert _classify_minimum_sql_tier("SELECT 1 FROM dual") == SqlTier.READ

    def test_select_for_update_is_write(self) -> None:
        assert _classify_minimum_sql_tier(
            "SELECT * FROM t FOR UPDATE"
        ) == SqlTier.WRITE

    def test_insert_is_write(self) -> None:
        assert _classify_minimum_sql_tier("INSERT INTO t VALUES (1)") == SqlTier.WRITE

    def test_explain_plan_is_write(self) -> None:
        assert (
            _classify_minimum_sql_tier("EXPLAIN PLAN FOR SELECT 1 FROM dual")
            == SqlTier.WRITE
        )

    def test_create_is_ddl(self) -> None:
        assert _classify_minimum_sql_tier("CREATE TABLE x (a NUMBER)") == SqlTier.DDL

    def test_alter_table_is_ddl(self) -> None:
        assert _classify_minimum_sql_tier("ALTER TABLE x ADD b NUMBER") == SqlTier.DDL

    def test_alter_session_is_full(self) -> None:
        assert (
            _classify_minimum_sql_tier("ALTER SESSION SET nls_date_format='YYYY-MM-DD'")
            == SqlTier.FULL
        )

    def test_grant_is_full(self) -> None:
        assert _classify_minimum_sql_tier("GRANT SELECT ON t TO u") == SqlTier.FULL

    def test_begin_is_full(self) -> None:
        assert _classify_minimum_sql_tier("BEGIN NULL; END;") == SqlTier.FULL

    def test_with_select_is_read(self) -> None:
        assert (
            _classify_minimum_sql_tier("WITH q AS (SELECT 1 FROM dual) SELECT * FROM q")
            == SqlTier.READ
        )

    def test_with_insert_is_write(self) -> None:
        sql_text = "WITH q AS (SELECT 1 FROM dual) INSERT INTO t SELECT * FROM q"
        assert _classify_minimum_sql_tier(sql_text) == SqlTier.WRITE

    def test_comment_stripped_before_classification(self) -> None:
        assert (
            _classify_minimum_sql_tier("-- comment\nSELECT 1 FROM dual")
            == SqlTier.READ
        )


class TestInvokedSqlTier:
    def test_maps_tool_names(self) -> None:
        assert _invoked_sql_tier("sql_read") == SqlTier.READ
        assert _invoked_sql_tier("sql_write") == SqlTier.WRITE
        assert _invoked_sql_tier("sql_ddl") == SqlTier.DDL
        assert _invoked_sql_tier("sql_full") == SqlTier.FULL

    def test_unknown_tool_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown SQL tool"):
            _invoked_sql_tier("sql_unknown")


class TestErrorMessages:
    def test_tier_check_message_mentions_required_tool(self) -> None:
        message = _tier_check_error_message(
            SqlTier.READ, SqlTier.WRITE, "sql_read"
        )
        assert "sql_write" in message
        assert "sql_read" in message

    def test_tenant_cap_message(self) -> None:
        message = _tenant_cap_error_message(SqlTier.WRITE, SqlTier.READ)
        assert "write" in message
        assert "read" in message
