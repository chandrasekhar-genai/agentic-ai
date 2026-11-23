"""Parse `terraform show -json tfplan` output."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Change:
    address: str
    type: str
    actions: list[str]
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    after_unknown: dict[str, Any] = field(default_factory=dict)
    reason: str | None = None

    @property
    def kind(self) -> str:
        a = self.actions
        if a == ["no-op"] or a == ["read"]:
            return "no-op"
        if "delete" in a and "create" in a:
            return "replace"
        return a[0]

    @property
    def values(self) -> dict[str, Any]:
        """Values after apply (or before, for deletes)."""
        return self.after if self.after is not None else (self.before or {})


@dataclass
class Plan:
    terraform_version: str
    changes: list[Change]

    def counts(self) -> dict[str, int]:
        out = {"create": 0, "update": 0, "replace": 0, "delete": 0}
        for c in self.changes:
            if c.kind in out:
                out[c.kind] += 1
        return out

    @property
    def effective(self) -> list[Change]:
        return [c for c in self.changes if c.kind != "no-op"]


def load_plan(path: str | Path) -> Plan:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    changes = []
    for rc in data.get("resource_changes", []):
        if rc.get("mode") != "managed":
            continue
        ch = rc["change"]
        changes.append(Change(
            address=rc["address"],
            type=rc["type"],
            actions=ch["actions"],
            before=ch.get("before"),
            after=ch.get("after"),
            after_unknown=ch.get("after_unknown") or {},
            reason=rc.get("action_reason"),
        ))
    return Plan(data.get("terraform_version", "?"), changes)
