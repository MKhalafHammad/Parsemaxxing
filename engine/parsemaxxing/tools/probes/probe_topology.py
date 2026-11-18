"""Read-only topology probe (design 7.1 auto-discovery; Q13 and Q14 read parts; D10 versions).

Point it at any lab node with the read token. It reads server/info, server/roles, the indexer
cluster, search head cluster and deployment server endpoints, and prints what each returns:
status, entry counts and the content keys (never values that could name a host). Deployment
clients are summarised by the fields that could tell a universal forwarder from a heavy
forwarder (Q14), with hashed names. Writes nothing.
Run: PMX_LAB_READ_TOKEN=... python -m parsemaxxing.tools.probes.probe_topology --host <node>
"""

import sys
from collections import Counter

from parsemaxxing.tools.probes import lab

ENDPOINTS = [
    "server/roles",
    "cluster/manager/info",
    "cluster/master/info",
    "cluster/config",
    "shcluster/config",
    "shcluster/member/info",
    "shcluster/captain/info",
    "shcluster/captain/members",
    "shcluster/status",
    "deployment/server/config",
    "deployment/server/serverclasses",
    "deployment/server/applications",
    "deployment/server/clients",
    "deployment/client/config",
]
# Client fields that might identify the client's package (Q14); the probe reports which exist.
UF_HINT_KEYS = ("package", "packageType", "splunkPlatform", "build", "utsname", "splunkVersion")


def classify_clients(rows: list[dict]) -> Counter:
    """Count clients by the value of each package-hinting key (values are product names)."""
    counts: Counter = Counter()
    for r in rows:
        c = r.get("content", {})
        for key in UF_HINT_KEYS:
            if key in c and key not in ("utsname", "splunkVersion"):
                counts[f"{key}={c[key]}"] += 1
            elif key in c:
                counts[f"{key} present"] += 1
    return counts


def main() -> int:
    args = lab.parser(__doc__.splitlines()[0]).parse_args()
    service = lab.connect(args, lab.READ_TOKEN_ENV)
    me = lab.whoami(service, lab.READ_TOKEN_ENV)
    if me is None:
        return 1
    lab.check_version(service)
    roles = lab.entries(service, "server/roles")
    print(f"server roles: {roles[0]['content'].get('role_list') if roles else 'unreadable'}")
    for path in ENDPOINTS:
        status, rows = lab.try_entries(service, path)
        print(f"{path}: {status}, entries={len(rows)}, keys={lab.keys_of(rows)[:40]}")
        if path == "deployment/server/clients" and rows:
            names = [lab.anon(r.get("name")) for r in rows]
            print(f"  clients (hashed): {names[:20]}")
            for label, n in sorted(classify_clients(rows).items()):
                print(f"  {label}: {n}")
        if path == "deployment/server/serverclasses" and rows:
            for r in rows:
                c = r.get("content", {})
                wl = [k for k in c if k.startswith(("whitelist.", "blacklist."))]
                print(f"  serverclass {r.get('name')}: filter keys={wl}")
        if path == "shcluster/captain/members" and rows:
            print(f"  members: {[lab.anon(r.get('name')) for r in rows]}")
    caps = sorted(me.get("capabilities", []))
    print(f"read token capabilities ({len(caps)}): {caps}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
