# Third-party notices

This file summarizes licenses for notable dependencies of **Oracle Database MCP Server** (this repository). It is provided for convenience. For authoritative terms, see each project’s license files and the package metadata on PyPI. **This is not legal advice.**

## This repository

Original source code in this repository is released under the **MIT License** — see [LICENSE](LICENSE).

## Python dependencies declared in `requirements.txt`

### `mcp` (Model Context Protocol Python SDK)

- **License:** MIT (per [PyPI: mcp](https://pypi.org/project/mcp/))
- **Homepage / source:** [modelcontextprotocol/python-sdk](https://github.com/modelcontextprotocol/python-sdk)

### `rich`

- **License:** MIT (per [PyPI: rich](https://pypi.org/project/rich/))
- **Homepage / source:** [Textualize/rich](https://github.com/Textualize/rich)

### `oracledb` (`python-oracledb`)

- **License:** **UPL-1.0 OR Apache-2.0** (dual-licensed; you may choose either — per [PyPI: oracledb](https://pypi.org/project/oracledb/) and [python-oracledb license documentation](https://python-oracledb.readthedocs.io/en/stable/license.html))
- **License text (upstream):** [oracle/python-oracledb `LICENSE.txt`](https://github.com/oracle/python-oracledb/blob/main/LICENSE.txt)
- **Third-party notices (upstream):** [oracle/python-oracledb `THIRD_PARTY_LICENSES.txt`](https://github.com/oracle/python-oracledb/blob/main/THIRD_PARTY_LICENSES.txt)
- **NOTICE (upstream):** [oracle/python-oracledb `NOTICE.txt`](https://github.com/oracle/python-oracledb/blob/main/NOTICE.txt)

Installing `oracledb` pulls in **transitive** dependencies (for example `cryptography`, `typing_extensions`). Their licenses are defined in each package’s metadata on PyPI and in upstream repositories. If you redistribute a **binary** artifact (for example a Docker image with dependencies pre-installed), follow the attribution and notice requirements of **all** included packages.

## Summary

| Component | Included in this repo? | License (summary) |
| --- | --- | --- |
| This project’s source | Yes | MIT |
| `mcp`, `rich`, `oracledb` (via pip) | No (installed by user / CI) | Per PyPI / upstream |
