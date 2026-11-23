"""Build inventory.csv from Azure Resource Graph and Azure Monitor using the az CLI.

    az login   (or azure/login with OIDC in CI)
    python scripts/build_inventory.py --subscription <id> > inventory.csv

Needs Reader on the subscription. CPU comes from platform metrics
("Percentage CPU", 30 days, hourly). Memory needs VM insights / Azure Monitor
Agent, so AvgMemPct30d is left empty and the rightsizing rule flags it.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

KQL = Path(__file__).resolve().parent.parent / "kql"
AZ = shutil.which("az") or "az"


def az(*args: str) -> object:
    out = subprocess.run([AZ, *args, "-o", "json"], check=True, capture_output=True, text=True).stdout  # noqa: S603
    return json.loads(out or "null")


def graph(query_file: str, subscription: str) -> list[dict]:
    query = (KQL / query_file).read_text(encoding="utf-8")
    rows, skip = [], None
    while True:
        args = ["graph", "query", "-q", query, "--subscriptions", subscription, "--first", "1000"]
        if skip:
            args += ["--skip-token", skip]
        page = az(*args)
        rows += page["data"]
        skip = page.get("skip_token")
        if not skip:
            return rows


def cpu_stats(resource_id: str, days: int = 30) -> tuple[str, str]:
    end = datetime.now(UTC)
    start = end - timedelta(days=days)
    data = az("monitor", "metrics", "list", "--resource", resource_id, "--metric", "Percentage CPU",
              "--interval", "PT1H", "--aggregation", "Average", "Maximum",
              "--start-time", start.isoformat(), "--end-time", end.isoformat())
    points = [p for ts in data["value"][0]["timeseries"] for p in ts["data"]] if data["value"] else []
    avgs = [p["average"] for p in points if p.get("average") is not None]
    maxes = [p["maximum"] for p in points if p.get("maximum") is not None]
    if not avgs:
        return "", ""
    return f"{sum(avgs) / len(avgs):.1f}", f"{max(maxes):.1f}"


def tags(t: dict | None) -> str:
    return ";".join(f"{k}={v}" for k, v in (t or {}).items())


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--subscription", required=True)
    args = p.parse_args()

    w = csv.writer(sys.stdout)
    w.writerow(["ResourceId", "Name", "Type", "Sku", "Location", "State",
                "AvgCpuPct30d", "MaxCpuPct30d", "AvgMemPct30d", "Attached", "Tags"])

    for vm in graph("vms.kql", args.subscription):
        state = vm["power"].replace("PowerState/", "")
        avg, mx = cpu_stats(vm["id"]) if state == "running" else ("", "")
        w.writerow([vm["id"], vm["name"], vm["type"], vm["size"], vm["location"], state, avg, mx, "", "",
                    tags(vm.get("tags"))])

    for d in graph("orphaned_disks.kql", args.subscription):
        w.writerow([d["id"], d["name"], d["type"], d["sku"], d["location"], "unattached", "", "", "", "false",
                    tags(d.get("tags"))])

    for ip in graph("orphaned_public_ips.kql", args.subscription):
        w.writerow([ip["id"], ip["name"], ip["type"], ip["sku"], ip["location"], "unassociated", "", "", "", "false",
                    tags(ip.get("tags"))])


if __name__ == "__main__":
    main()
