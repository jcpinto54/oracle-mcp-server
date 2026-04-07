"""
Tenant configuration: SQL privilege tier enum, JSON validation, and DSN building.
"""

from enum import IntEnum
from typing import Any, Dict


class SqlTier(IntEnum):
    """Cumulative SQL privilege tiers (higher value includes all lower)."""
    READ = 0
    WRITE = 1
    DDL = 2
    FULL = 3


def _parse_sql_max_tier(raw_value: Any, tenant_id: str) -> SqlTier:
    if raw_value is None:
        return SqlTier.FULL
    if not isinstance(raw_value, str):
        raise ValueError(
            f'Tenant "{tenant_id}": "sql_max_tier" must be a string or omitted'
        )
    normalized = raw_value.strip().lower()
    mapping = {
        "read": SqlTier.READ,
        "write": SqlTier.WRITE,
        "ddl": SqlTier.DDL,
        "full": SqlTier.FULL,
    }
    if normalized not in mapping:
        raise ValueError(
            f'Tenant "{tenant_id}": "sql_max_tier" must be one of '
            f'"read", "write", "ddl", "full" (got {raw_value!r})'
        )
    return mapping[normalized]


def _normalize_tenant_config(
    tenant_id: str,
    raw_config: Any,
) -> Dict[str, Any]:
    """Validate and normalize a single tenant connection block."""
    if not isinstance(raw_config, dict):
        raise ValueError(
            f'Tenant "{tenant_id}": connection must be a JSON object'
        )

    required_string_keys = ("host", "username", "password")
    for key in required_string_keys:
        if key not in raw_config:
            raise ValueError(f'Tenant "{tenant_id}": missing required field "{key}"')
        value = raw_config[key]
        if value is None or (isinstance(value, str) and not value.strip()):
            raise ValueError(
                f'Tenant "{tenant_id}": "{key}" must be a non-empty string'
            )
        if not isinstance(value, str):
            raise ValueError(f'Tenant "{tenant_id}": "{key}" must be a string')

    if "port" not in raw_config:
        raise ValueError(f'Tenant "{tenant_id}": missing required field "port"')
    try:
        port = int(raw_config["port"])
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f'Tenant "{tenant_id}": "port" must be an integer'
        ) from exc
    if port < 1 or port > 65535:
        raise ValueError(f'Tenant "{tenant_id}": "port" must be between 1 and 65535')

    service_name = raw_config.get("service_name")
    sid = raw_config.get("sid")

    if service_name is not None and not isinstance(service_name, str):
        raise ValueError(f'Tenant "{tenant_id}": "service_name" must be a string or null')
    if sid is not None and not isinstance(sid, str):
        raise ValueError(f'Tenant "{tenant_id}": "sid" must be a string or null')

    service_name_clean = service_name.strip() if service_name else ""
    sid_clean = sid.strip() if sid else ""

    if service_name_clean and sid_clean:
        raise ValueError(
            f'Tenant "{tenant_id}": set exactly one of "service_name" or "sid", not both'
        )
    if not service_name_clean and not sid_clean:
        raise ValueError(
            f'Tenant "{tenant_id}": must set either "service_name" or "sid" (non-empty)'
        )

    sql_max_tier = _parse_sql_max_tier(raw_config.get("sql_max_tier"), tenant_id)

    normalized: Dict[str, Any] = {
        "host": raw_config["host"].strip(),
        "port": port,
        "username": raw_config["username"].strip(),
        "password": raw_config["password"],
        "sql_max_tier": sql_max_tier,
    }
    if service_name_clean:
        normalized["service_name"] = service_name_clean
        normalized["sid"] = None
    else:
        normalized["service_name"] = None
        normalized["sid"] = sid_clean

    return normalized


def _parse_tenants(config: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Parse and validate the top-level tenants map."""
    if "tenants" not in config:
        raise ValueError('Configuration must contain a "tenants" object')
    tenants_raw = config["tenants"]
    if not isinstance(tenants_raw, dict) or len(tenants_raw) == 0:
        raise ValueError('"tenants" must be a non-empty object')

    tenant_configs: Dict[str, Dict[str, Any]] = {}
    for tenant_id, raw in tenants_raw.items():
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("Each tenant key must be a non-empty string")
        stable_id = tenant_id.strip()
        if stable_id in tenant_configs:
            raise ValueError(f'Duplicate tenant id after trimming: "{stable_id}"')
        tenant_configs[stable_id] = _normalize_tenant_config(stable_id, raw)

    return tenant_configs


def _build_dsn(tenant_config: Dict[str, Any]) -> str:
    host = tenant_config["host"]
    port = tenant_config["port"]
    if tenant_config.get("service_name"):
        return f"{host}:{port}/{tenant_config['service_name']}"
    return f"{host}:{port}/{tenant_config['sid']}"
