#!/usr/bin/env python3
"""Give cAdvisor metrics real container NAMES on Docker Desktop / macOS.

cAdvisor can't resolve container names inside the Docker Desktop VM (it needs the
containerd socket, which isn't exposed), so its metrics only carry the raw cgroup
`id`. This script bridges that gap with Prometheus relabeling:

  1. read the current `id -> name` mapping from `docker ps`
  2. write it as `metric_relabel_configs` on the cadvisor scrape job, adding a
     `container` label to every cAdvisor series
  3. hot-reload Prometheus (needs --web.enable-lifecycle, already set in compose)

Run it after `docker compose up` and after any `up --build app` (the app's
container id changes on rebuild):

    uv run python ops/scripts/relabel_containers.py
"""

import pathlib
import subprocess
import sys
import urllib.request

import yaml

PROM_YML = pathlib.Path(__file__).resolve().parents[1] / "prometheus" / "prometheus.yml"
PROM_RELOAD_URL = "http://localhost:9090/-/reload"


def docker_id_name_pairs():
    """Return [(full_container_id, name), ...] from the local Docker daemon."""
    out = subprocess.run(
        ["docker", "ps", "--no-trunc", "--format", "{{.ID}}\t{{.Names}}"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    pairs = []
    for line in out.splitlines():
        cid, _, name = line.partition("\t")
        if cid and name:
            pairs.append((cid, name))
    return pairs


def build_relabel_rules(pairs):
    # First rule: default `container` to the 12-char short id (so unknown
    # containers still get a readable-ish label). Later rules override it.
    rules = [
        {
            "source_labels": ["id"],
            "regex": "/docker/(.{12}).*",
            "target_label": "container",
            "replacement": "${1}",
        }
    ]
    # One override per known container: full id -> friendly name.
    for cid, name in pairs:
        rules.append({
            "source_labels": ["id"],
            "regex": f"/docker/{cid}",
            "target_label": "container",
            "replacement": name,
        })
    return rules


def main():
    pairs = docker_id_name_pairs()
    if not pairs:
        sys.exit("No running containers found (is the stack up?).")

    config = yaml.safe_load(PROM_YML.read_text())
    jobs = config.get("scrape_configs", [])
    cadvisor = next((j for j in jobs if j.get("job_name") == "cadvisor"), None)
    if cadvisor is None:
        sys.exit("No 'cadvisor' scrape job found in prometheus.yml.")

    cadvisor["metric_relabel_configs"] = build_relabel_rules(pairs)
    PROM_YML.write_text(yaml.safe_dump(config, sort_keys=False))
    print(f"Wrote {len(pairs)} name mappings to {PROM_YML}")
    for cid, name in pairs:
        print(f"  {cid[:12]} -> {name}")

    # Hot-reload Prometheus so the new labels take effect without a restart.
    try:
        urllib.request.urlopen(urllib.request.Request(PROM_RELOAD_URL, method="POST"), timeout=5)
        print("Prometheus reloaded. New graphs will show container names within a scrape cycle.")
    except Exception as e:  # noqa: BLE001
        print(f"WARNING: could not reload Prometheus at {PROM_RELOAD_URL}: {e}")
        print("Is the stack up? You can reload manually: curl -X POST localhost:9090/-/reload")


if __name__ == "__main__":
    main()
