"""Landing-zone guardrails evaluated against planned values.

These complement Checkov: Checkov checks the code against generic benchmarks;
these check *this change* against *your* platform rules (regions, tags,
destructive operations on stateful resources). Configure in .tfreview.toml.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .plan import Change, Plan

SEVERITY_ORDER = {"high": 3, "medium": 2, "low": 1}

STATEFUL_TYPES = (
    "azurerm_storage_account", "azurerm_mssql_server", "azurerm_mssql_database",
    "azurerm_postgresql_flexible_server", "azurerm_mysql_flexible_server", "azurerm_cosmosdb_account",
    "azurerm_key_vault", "azurerm_kubernetes_cluster", "azurerm_resource_group",
    "azurerm_managed_disk", "azurerm_redis_cache", "azurerm_search_service",
)
PUBLIC_ACCESS_TYPES = (
    "azurerm_storage_account", "azurerm_key_vault", "azurerm_cognitive_account", "azurerm_search_service",
    "azurerm_mssql_server", "azurerm_postgresql_flexible_server", "azurerm_container_registry",
    "azurerm_cosmosdb_account",
)
ADMIN_PORTS = {"22", "3389"}
ANY_SOURCE = {"*", "0.0.0.0/0", "internet", "any"}


@dataclass
class Config:
    allowed_locations: list[str] = field(default_factory=lambda: ["uaenorth", "uaecentral"])
    required_tags: list[str] = field(default_factory=lambda: ["owner", "env", "cost-center"])
    fail_on: str = "high"
    ignore: list[str] = field(default_factory=list)  # rule ids or "rule_id:address"

    @classmethod
    def load(cls, path: str | Path | None) -> Config:
        if not path or not Path(path).exists():
            return cls()
        data = tomllib.loads(Path(path).read_text(encoding="utf-8")).get("tfreview", {})
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class Finding:
    rule: str
    severity: str
    address: str
    message: str


def _norm(v: Any) -> str:
    return str(v).strip().lower().replace(" ", "")


def evaluate(plan: Plan, cfg: Config) -> list[Finding]:
    out: list[Finding] = []
    allowed = {_norm(x) for x in cfg.allowed_locations}
    for c in plan.effective:
        v = c.values
        out += _destructive(c)
        if c.kind in {"create", "update", "replace"}:
            loc = v.get("location")
            if isinstance(loc, str) and allowed and _norm(loc) not in allowed:
                regions = ", ".join(cfg.allowed_locations)
                out.append(Finding("allowed-locations", "high", c.address,
                                   f"location `{loc}` is outside the allowed regions ({regions})"))
            out += _tags(c, cfg)
            out += _public_access(c)
            out += _storage(c)
            out += _nsg(c)
            out += _key_vault(c)
            out += _aks(c)
    return [f for f in out if f.rule not in cfg.ignore and f"{f.rule}:{f.address}" not in cfg.ignore]


def _destructive(c: Change) -> list[Finding]:
    if c.kind in {"delete", "replace"} and c.type in STATEFUL_TYPES:
        why = f" ({c.reason.replace('_', ' ')})" if c.reason else ""
        return [Finding("destructive-change", "high", c.address,
                        f"**{c.kind}** of a stateful resource{why}; data loss is likely unless this is intended")]
    return []


def _tags(c: Change, cfg: Config) -> list[Finding]:
    if "tags" not in c.values and "tags" not in c.after_unknown:
        return []
    tags = {k.lower() for k in (c.values.get("tags") or {})}
    missing = [t for t in cfg.required_tags if t.lower() not in tags]
    if missing and not c.after_unknown.get("tags"):
        return [Finding("required-tags", "medium", c.address, f"missing required tags: {', '.join(missing)}")]
    return []


def _public_access(c: Change) -> list[Finding]:
    if c.type in PUBLIC_ACCESS_TYPES and c.values.get("public_network_access_enabled") is True:
        return [Finding("public-network-access", "high", c.address,
                        "`public_network_access_enabled = true`; use private endpoints")]
    return []


def _storage(c: Change) -> list[Finding]:
    if c.type != "azurerm_storage_account":
        return []
    v, out = c.values, []
    if v.get("min_tls_version") not in (None, "TLS1_2", "TLS1_3"):
        out.append(Finding("storage-tls", "medium", c.address, f"min_tls_version is `{v.get('min_tls_version')}`"))
    if v.get("allow_nested_items_to_be_public") is True:
        out.append(Finding("storage-public-blobs", "high", c.address, "anonymous blob access is allowed"))
    if v.get("shared_access_key_enabled") is True:
        out.append(Finding("storage-shared-key", "low", c.address,
                           "shared key auth enabled; prefer Entra ID (`shared_access_key_enabled = false`)"))
    return out


def _port_open(spec: str) -> bool:
    spec = spec.strip()
    if spec == "*":
        return True
    if "-" in spec:
        lo, _, hi = spec.partition("-")
        if lo.isdigit() and hi.isdigit():
            return any(int(lo) <= int(p) <= int(hi) for p in ADMIN_PORTS)
    return spec in ADMIN_PORTS


def _open_admin(rule: dict[str, Any]) -> bool:
    if _norm(rule.get("direction")) != "inbound" or _norm(rule.get("access")) != "allow":
        return False
    sources = {_norm(rule.get("source_address_prefix") or "")}
    sources |= {_norm(s) for s in rule.get("source_address_prefixes") or []}
    ports = [str(rule.get("destination_port_range") or "")]
    ports += [str(p) for p in rule.get("destination_port_ranges") or []]
    return bool(sources & ANY_SOURCE) and any(_port_open(p) for p in ports)


def _nsg(c: Change) -> list[Finding]:
    rules: list[dict[str, Any]] = []
    if c.type == "azurerm_network_security_rule":
        rules = [c.values]
    elif c.type == "azurerm_network_security_group":
        rules = c.values.get("security_rule") or []
    return [Finding("nsg-open-admin-port", "high", c.address,
                    f"rule `{r.get('name')}` allows SSH/RDP from the internet; use Bastion or JIT access")
            for r in rules if _open_admin(r)]


def _key_vault(c: Change) -> list[Finding]:
    if c.type == "azurerm_key_vault" and c.values.get("purge_protection_enabled") is False:
        return [Finding("keyvault-purge-protection", "medium", c.address, "purge protection is disabled")]
    return []


def _aks(c: Change) -> list[Finding]:
    if c.type != "azurerm_kubernetes_cluster":
        return []
    out = []
    if c.values.get("local_account_disabled") is False:
        out.append(Finding("aks-local-accounts", "medium", c.address, "local accounts enabled; use Entra ID RBAC"))
    if c.values.get("private_cluster_enabled") is False and not c.values.get("api_server_access_profile"):
        out.append(Finding("aks-public-api", "medium", c.address,
                           "public API server with no authorized IP ranges"))
    return out


def blocking(findings: list[Finding], fail_on: str) -> list[Finding]:
    if fail_on == "never":
        return []
    level = SEVERITY_ORDER[fail_on]
    return [f for f in findings if SEVERITY_ORDER[f.severity] >= level]
