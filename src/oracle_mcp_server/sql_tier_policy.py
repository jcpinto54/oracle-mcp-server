"""
Heuristic SQL parsing and minimum tier classification for tiered MCP SQL tools.
"""

import re
from typing import List, Optional, Tuple

from .tenant_config import SqlTier


def _strip_leading_sql_comments_and_whitespace(sql_text: str) -> str:
    """Remove leading whitespace, line comments (--), and block comments (/* */)."""
    idx = 0
    sql_len = len(sql_text)
    while idx < sql_len:
        if sql_text[idx].isspace():
            idx += 1
            continue
        if sql_text.startswith("--", idx):
            line_end = sql_text.find("\n", idx)
            if line_end == -1:
                return ""
            idx = line_end + 1
            continue
        if sql_text.startswith("/*", idx):
            end_comment = sql_text.find("*/", idx + 2)
            if end_comment == -1:
                return ""
            idx = end_comment + 2
            continue
        break
    return sql_text[idx:]


def _split_top_level_statement_segments(sql_text: str) -> List[str]:
    """
    Split SQL on semicolons that are not inside single-quoted literals ('' escapes).
    Best-effort; not a full SQL parser.
    """
    segments: List[str] = []
    current_chars: List[str] = []
    sql_len = len(sql_text)
    in_single_quote = False
    position = 0
    while position < sql_len:
        char = sql_text[position]
        if char == "'":
            current_chars.append(char)
            if in_single_quote and position + 1 < sql_len and sql_text[position + 1] == "'":
                current_chars.append("'")
                position += 2
                continue
            in_single_quote = not in_single_quote
            position += 1
            continue
        if char == ";" and not in_single_quote:
            segments.append("".join(current_chars))
            current_chars = []
            position += 1
            continue
        current_chars.append(char)
        position += 1
    segments.append("".join(current_chars))
    return segments


def _non_empty_statement_count(sql_text: str) -> int:
    """Count distinct non-empty statements (top-level ';' split, heuristic)."""
    trimmed = (sql_text or "").replace("\r\n", "\n").strip()
    if not trimmed:
        return 0
    if trimmed.upper().startswith("BEGIN"):
        return 1
    segments = _split_top_level_statement_segments(trimmed)
    return sum(1 for segment in segments if segment.strip())


def _invoked_sql_tier(tool_name: str) -> SqlTier:
    mapping = {
        "sql_read": SqlTier.READ,
        "sql_write": SqlTier.WRITE,
        "sql_ddl": SqlTier.DDL,
        "sql_full": SqlTier.FULL,
    }
    if tool_name not in mapping:
        raise ValueError(f"Unknown SQL tool: {tool_name}")
    return mapping[tool_name]


def _first_reserved_words(sql_head: str) -> Tuple[Optional[str], Optional[str]]:
    """First one or two SQL reserved words at the start of sql_head (already comment-stripped)."""
    match = re.match(
        r'(?i)^\s*([A-Z_][A-Z0-9_$]*)(?:\s+([A-Z_][A-Z0-9_$]*))?',
        sql_head,
    )
    if not match:
        return None, None
    return match.group(1).upper(), match.group(2).upper() if match.group(2) else None


def _has_for_update_suffix(sql_text: str) -> bool:
    return bool(re.search(r"\bFOR\s+UPDATE\b", sql_text, re.IGNORECASE))


def _classify_minimum_sql_tier(query_text: str) -> SqlTier:
    """
    Minimum SqlTier required for this SQL (single-statement assumption for classified tools).
    Unknown or admin-style statements map to FULL.
    """
    stripped_full = (query_text or "").replace("\r\n", "\n").strip()
    if not stripped_full:
        return SqlTier.READ

    head = _strip_leading_sql_comments_and_whitespace(stripped_full)
    if not head:
        return SqlTier.READ

    first_word, second_word = _first_reserved_words(head)
    if first_word is None:
        return SqlTier.FULL

    # PL/SQL or opaque
    if first_word in ("BEGIN", "DECLARE"):
        return SqlTier.FULL

    # Transaction / DCL
    if first_word in ("COMMIT", "ROLLBACK", "SAVEPOINT", "GRANT", "REVOKE"):
        return SqlTier.FULL

    if first_word == "CALL":
        return SqlTier.FULL

    if first_word == "ALTER":
        if second_word in ("SESSION", "SYSTEM"):
            return SqlTier.FULL
        return SqlTier.DDL

    if first_word == "WITH":
        if re.search(r"\)\s*(INSERT|UPDATE|DELETE|MERGE)\b", stripped_full, re.IGNORECASE):
            return SqlTier.WRITE
        if re.search(r"\)\s*SELECT\b", stripped_full, re.IGNORECASE):
            return SqlTier.READ
        return SqlTier.WRITE

    if first_word == "EXPLAIN" and second_word == "PLAN":
        return SqlTier.WRITE

    if first_word in ("INSERT", "UPDATE", "DELETE", "MERGE"):
        return SqlTier.WRITE

    if first_word == "LOCK" and second_word == "TABLE":
        return SqlTier.WRITE

    if first_word == "SELECT":
        if _has_for_update_suffix(stripped_full):
            return SqlTier.WRITE
        return SqlTier.READ

    if first_word in ("CREATE", "DROP", "TRUNCATE", "RENAME"):
        return SqlTier.DDL

    if first_word == "COMMENT" and second_word == "ON":
        return SqlTier.DDL

    return SqlTier.FULL


def _tier_check_error_message(
    invoked: SqlTier,
    required: SqlTier,
    tool_name: str,
) -> str:
    tier_tool = {
        SqlTier.READ: "sql_read",
        SqlTier.WRITE: "sql_write",
        SqlTier.DDL: "sql_ddl",
        SqlTier.FULL: "sql_full",
    }
    need = tier_tool[required]
    return (
        f"This statement requires {need} or a higher tier (minimum tier {need}); "
        f"{tool_name} is not sufficient."
    )


def _tenant_cap_error_message(
    required: SqlTier,
    tenant_max: SqlTier,
) -> str:
    tier_name = {SqlTier.READ: "read", SqlTier.WRITE: "write", SqlTier.DDL: "ddl", SqlTier.FULL: "full"}
    return (
        f"This statement needs tier {tier_name[required]} but the tenant sql_max_tier cap is "
        f"{tier_name[tenant_max]}."
    )
