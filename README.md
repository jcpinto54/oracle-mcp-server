# Oracle Database MCP Server

> A Model Context Protocol (MCP) server that enables AI assistants to execute SQL queries and explore Oracle databases through a standardized interface.

[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![MCP](https://img.shields.io/badge/MCP-Protocol-orange.svg)](https://modelcontextprotocol.io/)

A Model Context Protocol (MCP) server that provides tiered SQL execution for Oracle databases. Four cumulative tools (`sql_read`, `sql_write`, `sql_ddl`, `sql_full`) enforce statement categories before execution; optional per-tenant `sql_max_tier` caps risk even when clients call `sql_full`. **SQL injection remains a critical threat** whenever the model builds `query` from chat, user paste, or documents: malicious fragments can change what the database executes (exfiltration, destructive DML/DDL, privilege abuse). **Binds (`:1`, `:2`, … + `params`) are mandatory for variable data**; tier limits limit *what kind* of statement can run, not *logic* inside a single statement. Schema exploration and metadata use `sql_read` (for example against `USER_*` / `ALL_*` views); `EXPLAIN PLAN` uses `sql_write` because it writes to `PLAN_TABLE`.

## Maintainer

Maintainer: João Castro Pinto  
Forked from: Siddharth Arvind Singh

## 🚀 Core Features

### SQL Query Execution
- Tiered tools: `sql_read` (read-shaped SQL), `sql_write` ( + DML and `EXPLAIN PLAN`), `sql_ddl` (+ DDL), `sql_full` (break-glass, no classification)
- Single-statement enforcement for the three classified tools (best-effort `;` splitting outside string literals)
- **Bind parameters (`params`)** for any data that is not a fixed literal you fully control—treating this as optional is how SQL injection happens in LLM workflows
- Automatic result formatting with configurable row limits
- Classified tools auto-commit after successful execution; `sql_full` does not auto-commit (use `COMMIT` / `ROLLBACK` in SQL as needed)

### MCP Protocol Integration
- Full Model Context Protocol (MCP) compliance
- Tools: `list_tenants` (discovery) and `sql_read` / `sql_write` / `sql_ddl` / `sql_full`
- Async/await support for concurrent operations
- Comprehensive error handling and logging

## 📋 Requirements

- Python 3.8+
- Oracle Database reachable from the machine running this server (see [python-oracledb installation](https://python-oracledb.readthedocs.io/en/latest/user_guide/installation.html) for supported environments)
- [`python-oracledb`](https://pypi.org/project/oracledb/) (`oracledb` on PyPI), installed automatically with the package via `pyproject.toml` (or legacy `requirements.txt` if you still use that file)
- MCP-compatible client (Cursor, Claude Desktop, etc.)

## 🛠️ Quick Start

1. **Clone the repository**:
   ```bash
   git clone https://github.com/jcpinto54/oracle-mcp-server.git
   cd oracle-mcp-server
   ```

2. **Run the bootstrap script** (recommended):
   ```bash
   python scripts/bootstrap.py
   ```
   
   This will:
   - Check Python version compatibility
   - Install the package in editable mode with test extras (`pip install -e ".[test]"`), pulling runtime dependencies from `pyproject.toml`
   - Create `config.json` in the repository root from `config/config.example.json`
   - Verify that the `oracledb` Python package can be imported

3. **Configure database connections**:
   ```bash
   # Edit config.json: add one entry per Oracle user/schema under "tenants"
   # Use your preferred editor to modify config.json
   ```

4. **Run the server** (pass the path to `config.json`; repo root after bootstrap is fine):
   ```bash
   oracle-mcp-server config.json
   ```
   
   Equivalent module form:
   ```bash
   python -m oracle_mcp_server config.json
   ```
   
   Or set `ORACLE_MCP_CONFIG` to the config file path and run with no extra arguments:
   ```bash
   export ORACLE_MCP_CONFIG=/absolute/path/to/config.json
   oracle-mcp-server
   ```

### Install from PyPI with `uvx` (after publishing)

Once the package is on [PyPI](https://pypi.org/project/oracle-mcp-server/) (see **Maintainers — releasing** below), run it without cloning:

```bash
uvx oracle-mcp-server /absolute/path/to/config.json
```

Use `env` in the MCP client to set `ORACLE_MCP_CONFIG` instead of a CLI argument if you prefer.

## 📁 Project Structure

```
oracle-mcp-server/
├── src/
│   └── oracle_mcp_server/     # Installable Python package
│       ├── __init__.py
│       ├── __main__.py        # Entry point for `oracle-mcp-server` / `python -m oracle_mcp_server`
│       ├── server.py          # MCP server, tools, SQL execution
│       ├── tenant_config.py   # Tenants, DSN, sql_max_tier
│       └── sql_tier_policy.py # SQL tier classification
├── config/
│   └── config.example.json    # Example configuration (copy to root `config.json`)
├── scripts/
│   └── bootstrap.py           # Dependency + editable install + config copy
├── tests/                     # pytest suite (unit + mocked server tests)
├── pyproject.toml             # Package metadata + src layout (use with `pip install -e .`)
├── config.json                # Local server configuration (created by bootstrap; not in git)
├── requirements.txt           # Optional legacy mirror; primary deps are in pyproject.toml
├── THIRD_PARTY_NOTICES.md     # Third-party and dependency license summary
├── README.md
└── LICENSE
```

## ⚙️ Configuration

You must point the server at a config file explicitly:

1. **First command-line argument** — path to `config.json` (recommended for `uvx` and MCP `args`), or  
2. **`ORACLE_MCP_CONFIG`** — absolute or relative path to the same file.

There is no implicit `config.json` in the current working directory.

The bootstrap script creates `config.json` in the **repository root** from [`config/config.example.json`](config/config.example.json). You can also copy that file manually and define **one entry per Oracle user/schema** under `tenants`. Each key is the `tenant_id` clients pass to the `sql_*` tools.

**Migration from older configs:** if you previously used a single top-level `database` object, move those fields under `tenants` using a stable id (for example `"prod"`).

```json
{
    "tenants": {
        "prod": {
            "host": "your-oracle-host",
            "port": 1521,
            "username": "prod-schema-user",
            "password": "your-password",
            "service_name": "YOUR_SERVICE",
            "sid": null
        },
        "uat": {
            "host": "uat-oracle-host",
            "port": 1521,
            "username": "uat-schema-user",
            "password": "your-password",
            "service_name": null,
            "sid": "YOUR_SID",
            "sql_max_tier": "ddl"
        }
    },
    "mcp": {
        "server_name": "oracle-sql-helper",
        "version": "1.0.0",
        "description": "Oracle Database MCP Server for SQL query execution",
        "max_results": 1000,
        "timeout_seconds": 30
    },
    "logging": {
        "level": "INFO",
        "file": "mcp_server.log"
    }
}
```

### Configuration Options

- **tenants**: Map of tenant id (string) to Oracle connection details. The id is what you pass as `tenant_id` to any `sql_*` tool.
  - `host`: Database server hostname/IP
  - `port`: Database port (usually 1521)
  - `username`: Database username (Oracle schema user for that tenant)
  - `password`: Database password
  - **Exactly one** of `service_name` or `sid` must be set to a non-empty string (the other should be `null`). Do not set both.
  - `sql_max_tier` (optional): Cap statements for this tenant: `read`, `write`, `ddl`, or `full` (default `full`). The server rejects work above the cap even if the client calls `sql_full`.

- **mcp**: MCP server settings
  - `max_results`: Maximum number of rows to return (default: 1000)
  - `timeout_seconds`: Query timeout in seconds (default: 30)

- **logging**: Logging configuration
  - `level`: Log level (DEBUG, INFO, WARNING, ERROR)
  - `file`: Log file name

## 🛠️ Available Tools

The MCP server exposes `list_tenants` plus four cumulative SQL tools. Tool descriptions sent to the LLM explain privileges; **least-privilege choice is enforced mainly by the MCP client** (prompts and which tools are registered). The server enforces tier- and cap-based **correctness**.

### list_tenants

Returns JSON listing configured tenants: `tenant_id`, `host`, `port`, `sql_max_tier`, and either `service_name` or `sid`. Passwords are never returned. Call this first so the client can choose a valid `tenant_id`.

**Parameters:** none.

### sql_read

Single SQL statement: read-oriented only (`SELECT`, read-safe `WITH … ) SELECT …`). No DML, DDL, `EXPLAIN PLAN`, PL/SQL, transaction control, or multi-statement scripts. Auto-commits after success.

### sql_write

Everything `sql_read` allows, plus DML (`INSERT`, `UPDATE`, `DELETE`, `MERGE`), `EXPLAIN PLAN` (writes to `PLAN_TABLE`), `SELECT … FOR UPDATE`, `LOCK TABLE`. One statement; auto-commit after success. Not for DDL, `GRANT`/`REVOKE`, PL/SQL, or `COMMIT`/`ROLLBACK` — use `sql_ddl` or `sql_full` as appropriate.

### sql_ddl

Everything `sql_write` allows, plus DDL-style statements (`CREATE`, `ALTER` except `ALTER SESSION` / `ALTER SYSTEM`, `DROP`, `TRUNCATE`, `RENAME`, `COMMENT ON …`). One statement; auto-commit after success. For session/server changes, grants, PL/SQL, scripts, or transaction commands, use `sql_full`.

### sql_full

Break-glass: **no** keyword classification. Allows multi-statement scripts, PL/SQL, `COMMIT` / `ROLLBACK`, `GRANT`, etc. Server **does not** auto-commit after execution. Still limited by per-tenant `sql_max_tier`.

**Shared parameters** (all `sql_*` tools):

- `tenant_id` (required): Tenant key from `list_tenants` / `config.json`
- `query` (required): SQL string (for classified tools, exactly one statement; see tier rules above)
- `params` (optional): Bind values for **parameterized SQL** — see below

**Parameterized queries (bind variables) — SQL injection defense**  

If you concatenate or f-string **any** external, user, or chat-derived text into `query`, an attacker (or a poisoned document the model reads) can inject SQL. Consequences include **unauthorized reads**, **mass updates/deletes**, **schema destruction**, and **privilege abuse**—even inside a single “allowed” tier. **Defense:** keep the SQL *shape* fixed in `query` and move *values* into **`params`**.

1. Put **positional** placeholders in `query`: Oracle style **` :1 `**, **` :2 `**, … for the first, second, … bind value.
2. Pass **`params`** as a JSON array of **strings**, in order: first element binds `:1`, second binds `:2`, etc.
3. If there are no placeholders, omit `params` or use `[]`.
4. Oracle will coerce string binds to numbers or dates where the column/type allows.
5. **Identifiers** (table/column names from user input) cannot be safely bound in plain SQL; avoid dynamic object names or enforce strict allowlists outside the LLM.

**Example** (`sql_read`): safer pattern — `query` = `SELECT customer_name FROM customer WHERE customer_id = :1 AND status = :2` with `params` = `["12345", "ACTIVE"]`. **Unsafe pattern:** ``WHERE customer_id = '{user_id}'`` built from chat text.

**Example** (`sql_read`; pass `tenant_id` with the tool invocation):

```sql
SELECT customer_name, account_balance 
FROM account a 
JOIN customer_node c ON a.customer_node_id = c.customer_node_id 
WHERE account_balance > 1000
```

**Metadata examples** (`sql_read`): list tables — `SELECT table_name FROM user_tables ORDER BY table_name`; columns — `user_tab_columns` / `all_tab_columns`. **Execution plan:** use `sql_write` with `EXPLAIN PLAN FOR ...` (and query `plan_table` / `DBMS_XPLAN` as needed).

### Migration from `execute_sql`

Replace the single tool with:

| Before (`execute_sql`) | Replacement |
| --- | --- |
| `SELECT`, read-safe metadata | `sql_read` |
| DML, `EXPLAIN PLAN`, `SELECT FOR UPDATE` | `sql_write` |
| DDL (`CREATE`, `ALTER TABLE`, …) | `sql_ddl` |
| Scripts, PL/SQL, `COMMIT`, `GRANT`, … | `sql_full` |

### Classification limits

Statement classification uses **heuristics** (leading keywords, `WITH` and `FOR UPDATE` patterns, top-level `;` outside quotes). It is **not** a full SQL parser; rare edge cases may mis-classify — use `sql_full` when necessary. Using a **higher** tool with a **lower-tier** statement is always allowed (cumulative tiers).

## 🔗 MCP Client Configuration

To use this server with an MCP client, add one of the following patterns.

**Published package (`uvx`)** — no venv or repo `cwd` required:

```json
{
  "mcpServers": {
    "oracle-sql-helper": {
      "command": "uvx",
      "args": ["oracle-mcp-server", "/absolute/path/to/config.json"],
      "env": {}
    }
  }
}
```

**Installed console script** — after `pip install oracle-mcp-server` or `pip install -e .`:

```json
{
  "mcpServers": {
    "oracle-sql-helper": {
      "command": "oracle-mcp-server",
      "args": ["/absolute/path/to/config.json"],
      "env": {}
    }
  }
}
```

**Development** — same Python you used for `pip install -e ".[test]"`:

```json
{
  "mcpServers": {
    "oracle-sql-helper": {
      "command": "python",
      "args": ["-m", "oracle_mcp_server", "/absolute/path/to/config.json"],
      "env": {}
    }
  }
}
```

**Config via environment** (any of the above commands may use empty `args` if you set `ORACLE_MCP_CONFIG` in `env`).

## Maintainers — releasing

1. Bump `version` in [`pyproject.toml`](pyproject.toml).
2. Commit and push, then create a version tag (for example `v1.0.1`).
3. GitHub Actions **Publish** workflow (on tag push) builds and uploads to PyPI using **trusted publishing** — register this repo on PyPI under the project’s publishing settings; see [`.github/workflows/publish.yml`](.github/workflows/publish.yml).
4. Verify [PyPI](https://pypi.org/project/oracle-mcp-server/) and smoke-test: `uvx oracle-mcp-server /path/to/config.json`.

## 🔒 Security Features

### SQL injection (highest priority for AI integrations)

- **Threat:** The model or client sends a `query` string. Embedding untrusted text (user questions, pasted logs, web/tool content) via string concatenation lets attackers **change query meaning**: broad `SELECT`s, `UNION`-based exfiltration, destructive `UPDATE`/`DELETE`, `DROP`, or sequences that defeat your intent.
- **Mitigation:** Use **binds** (`:1`, `:2`, … + `params`) for every value that is not a constant you authored. See **Parameterized queries** above. Educate prompts: “never put variable input in the query text.”
- **Limits of tiering:** `sql_read` / `sql_write` / `sql_ddl` / `sql_full` and `sql_max_tier` restrict **statement classes**, not **arbitrary SQL inside one statement**. Injection inside a `SELECT` can still leak the whole dataset readable by the schema user.
- **Identifiers:** Dynamic table/column names from users are not safely fixable with value binds alone; use fixed SQL or server-side allowlists.

### Other controls

- Tiered tools plus optional per-tenant `sql_max_tier` cap
- Secure credential management via configuration files
- Configurable result limits to prevent memory issues
- Comprehensive logging for audit trails
- Connection error handling; rollback on failed classified executions

## 📊 Performance Features

- Configurable result set limits (default: 1000 rows)
- Query timeout protection (default: 30 seconds)
- One lazy Oracle connection per tenant (reused for that tenant after first use)
- Async operation support

## 🐛 Troubleshooting

### Common Issues

1. **`oracledb` import or driver errors**:
   - Ensure dependencies are installed: `pip install -e .` or `pip install oracle-mcp-server` (or re-run `python scripts/bootstrap.py`)
   - Check Python version and `cryptography` (a dependency of `python-oracledb`)

2. **Connection timeout**:
   - Verify database host and port are correct
   - Check network connectivity
   - Verify database is running and accepting connections

3. **Authentication failed**:
   - Verify username and password
   - Check if account is locked or expired
   - Ensure proper privileges are granted

4. **TNS errors**:
   - Verify SID or service_name is correct
   - Check Oracle listener is running
   - Verify network configuration

### Debugging

Enable debug logging by setting log level to "DEBUG" in config.json:

```json
{
    "logging": {
        "level": "DEBUG",
        "file": "mcp_server.log"
    }
}
```

Check the log file `mcp_server.log` for detailed error messages.

## 📝 Sample Queries

Here are some sample queries you can try:

### Basic Account Information
```sql
SELECT account_id, account_balance, created_date 
FROM account 
WHERE account_balance > 100 
ORDER BY account_balance DESC
```

### Customer Account Summary
```sql
SELECT c.customer_name, COUNT(a.account_id) as account_count, 
       SUM(a.account_balance) as total_balance
FROM customer_node c
LEFT JOIN account a ON c.customer_node_id = a.customer_node_id
GROUP BY c.customer_name
HAVING COUNT(a.account_id) > 0
ORDER BY total_balance DESC
```

### Account History Analysis
```sql
SELECT ah.account_id, ah.transaction_type, ah.amount, ah.transaction_date
FROM account_history ah
WHERE ah.transaction_date >= SYSDATE - 30
ORDER BY ah.transaction_date DESC
```

## ⚡ Performance Tips

1. **Use Indexes**: Ensure proper indexes exist for your queries
2. **Limit Results**: Use the `max_results` configuration to prevent memory issues
3. **Parameterized queries**: Always bind variable **values** (`params`); never inline untrusted text into `query`. Improves plan reuse and avoids injection.
4. **Query analysis**: Use `sql_write` with `EXPLAIN PLAN` and `plan_table` (or `DBMS_XPLAN`) when you need execution plans
5. **Connection Pooling**: Consider implementing connection pooling for high-load scenarios

## Tests

Automated tests cover SQL tier heuristics, tenant configuration validation, and MCP server guardrails using mocks (no live Oracle required for the default run).

1. Install the package in editable mode with test dependencies:
   ```bash
   pip install -e ".[test]"
   ```
2. From the repository root, run:
   ```bash
   pytest
   ```

**Layout**

- `tests/unit/` — `sql_tier_policy` and `tenant_config` behavior
- `tests/server/` — tier enforcement, `call_tool` dispatch, and `_run_sql_sync` (fake connections/cursors)

**Extending**

- Prefer table-driven cases in unit tests for new classification or config rules.
- For execution paths, add fakes under `tests/server/` and avoid real `oracledb` connections unless you introduce optional integration tests.

Configuration for `pytest` (paths, `pythonpath`, asyncio mode) lives in [`pyproject.toml`](pyproject.toml) under `[tool.pytest.ini_options]`.

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Run tests: `pip install -e ".[test]"` then `pytest`
4. Commit your changes (`git commit -m 'Add some amazing feature'`)
5. Push to the branch (`git push origin feature/amazing-feature`)
6. Open a Pull Request

## 📄 License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

Per [LICENSE](LICENSE), this project’s source is released under the **MIT License**. It **depends on** third-party packages (for example `mcp`, `rich`, `python-oracledb`) that remain under their own licenses; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). **Oracle Client / Instant Client binaries are not distributed with this repository.** If you install or redistribute them separately, Oracle’s license terms apply. This paragraph is for transparency only and is not legal advice.

## 🆘 Support

For issues and questions:
1. Check the troubleshooting section
2. Review the log files
3. Verify `python-oracledb` is installed and that the host can reach Oracle over the network
4. Test database connectivity outside of MCP
5. Open an issue on GitHub
