"""
Unit tests for tenant configuration parsing and DSN building.
"""

import pytest

from oracle_mcp_server.tenant_config import SqlTier, _build_dsn, _parse_tenants


def _valid_tenant_block(service_name: bool = True) -> dict:
    if service_name:
        return {
            "host": " db.example.com ",
            "port": 1521,
            "username": " u1 ",
            "password": "pw",
            "service_name": "ORCL",
            "sid": None,
        }
    return {
        "host": "db.example.com",
        "port": 1521,
        "username": "u1",
        "password": "pw",
        "service_name": None,
        "sid": "ORCLSID",
    }


class TestParseTenantsSuccess:
    def test_normalizes_service_name_tenant(self) -> None:
        config = {"tenants": {"prod": _valid_tenant_block(True)}}
        tenants = _parse_tenants(config)
        assert "prod" in tenants
        prod = tenants["prod"]
        assert prod["host"] == "db.example.com"
        assert prod["port"] == 1521
        assert prod["username"] == "u1"
        assert prod["service_name"] == "ORCL"
        assert prod["sid"] is None
        assert prod["sql_max_tier"] == SqlTier.FULL

    def test_normalizes_sid_tenant(self) -> None:
        config = {"tenants": {"prod": _valid_tenant_block(False)}}
        tenants = _parse_tenants(config)
        prod = tenants["prod"]
        assert prod["service_name"] is None
        assert prod["sid"] == "ORCLSID"

    def test_sql_max_tier_parsing(self) -> None:
        block = _valid_tenant_block(True)
        block["sql_max_tier"] = "read"
        config = {"tenants": {"t": block}}
        assert _parse_tenants(config)["t"]["sql_max_tier"] == SqlTier.READ

    def test_trims_duplicate_keys_after_trim_raises(self) -> None:
        config = {
            "tenants": {
                " same ": _valid_tenant_block(True),
                "same": _valid_tenant_block(True),
            }
        }
        with pytest.raises(ValueError, match="Duplicate tenant id"):
            _parse_tenants(config)


class TestParseTenantsErrors:
    def test_missing_tenants_key(self) -> None:
        with pytest.raises(ValueError, match="tenants"):
            _parse_tenants({})

    def test_tenants_empty_object(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            _parse_tenants({"tenants": {}})

    def test_tenant_key_not_string(self) -> None:
        with pytest.raises(ValueError, match="tenant key"):
            _parse_tenants({"tenants": {123: _valid_tenant_block(True)}})

    def test_connection_not_object(self) -> None:
        with pytest.raises(ValueError, match="JSON object"):
            _parse_tenants({"tenants": {"x": []}})

    def test_missing_host(self) -> None:
        block = _valid_tenant_block(True)
        del block["host"]
        with pytest.raises(ValueError, match="host"):
            _parse_tenants({"tenants": {"x": block}})

    def test_empty_password(self) -> None:
        block = _valid_tenant_block(True)
        block["password"] = "  "
        with pytest.raises(ValueError, match="password"):
            _parse_tenants({"tenants": {"x": block}})

    def test_port_not_int(self) -> None:
        block = _valid_tenant_block(True)
        block["port"] = "nope"
        with pytest.raises(ValueError, match="port"):
            _parse_tenants({"tenants": {"x": block}})

    def test_port_out_of_range(self) -> None:
        block = _valid_tenant_block(True)
        block["port"] = 70000
        with pytest.raises(ValueError, match="65535"):
            _parse_tenants({"tenants": {"x": block}})

    def test_both_service_name_and_sid_set(self) -> None:
        block = _valid_tenant_block(True)
        block["sid"] = "X"
        with pytest.raises(ValueError, match="exactly one"):
            _parse_tenants({"tenants": {"x": block}})

    def test_neither_service_name_nor_sid(self) -> None:
        block = _valid_tenant_block(True)
        block["service_name"] = None
        block["sid"] = None
        with pytest.raises(ValueError, match="either"):
            _parse_tenants({"tenants": {"x": block}})

    def test_sql_max_tier_invalid_string(self) -> None:
        block = _valid_tenant_block(True)
        block["sql_max_tier"] = "admin"
        with pytest.raises(ValueError, match="sql_max_tier"):
            _parse_tenants({"tenants": {"x": block}})

    def test_sql_max_tier_wrong_type(self) -> None:
        block = _valid_tenant_block(True)
        block["sql_max_tier"] = 1
        with pytest.raises(ValueError, match="string or omitted"):
            _parse_tenants({"tenants": {"x": block}})


class TestBuildDsn:
    def test_service_name_dsn(self) -> None:
        tenant_cfg = {
            "host": "h",
            "port": 1521,
            "service_name": "SVC",
            "sid": None,
        }
        assert _build_dsn(tenant_cfg) == "h:1521/SVC"

    def test_sid_dsn(self) -> None:
        tenant_cfg = {
            "host": "h",
            "port": 1522,
            "service_name": None,
            "sid": "SID1",
        }
        assert _build_dsn(tenant_cfg) == "h:1522/SID1"
