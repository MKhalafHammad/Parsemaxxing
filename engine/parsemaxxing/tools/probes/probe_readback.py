"""Q17 (and the read-back halves of Q13 and Q23): what can be read back from one node over REST
to prove an add-on's effective settings?

Point it at each tier in turn (standalone, SHC member, heavy forwarder, HF-DS) with the read
token. For one app and one sourcetype it reads: the installed app (version, any hash-like
field), the stanza in the app's own context, in the search app's context and in the global
context (`-`), `properties/props`, the matching transforms, and the `eai:acl` owner app of each
answer, so the owner can see which app wins and whether a local/ copy is visible. Prints keys
and values of the named stanza only (probe stanzas carry no secrets). Writes nothing.
Run: PMX_LAB_READ_TOKEN=... python -m parsemaxxing.tools.probes.probe_readback \\
       --host <node> --app <app> --sourcetype <sourcetype> [--transform <name>]
"""

import re
import sys

from parsemaxxing.tools.probes import lab

NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:-]{0,99}")
SHOWN = re.compile(
    r"(TIME_|TZ|LINE_BREAKER|SHOULD_LINEMERGE|EXTRACT-|REPORT-|TRANSFORMS-|"
    r"FIELDALIAS-|EVAL-|KV_MODE|INDEXED_EXTRACTIONS|DELIMS|FIELDS|REGEX|"
    r"FORMAT|DEST_KEY|CHARSET|MAX_)"
)


def summarize(content: dict) -> dict:
    """The settings worth comparing, plus where Splunk says they came from."""
    acl = content.get("eai:acl") or {}
    out = {k: v for k, v in content.items() if SHOWN.match(k)}
    out["eai:appName"] = content.get("eai:appName") or acl.get("app")
    return out


def show(service, label: str, path: str, owner: str, app: str) -> None:
    status, rows = lab.try_entries(service, path, owner=owner, app=app)
    print(f"{label}: {status}")
    for r in rows[:1]:
        for k, v in sorted(summarize(r.get("content", {})).items()):
            print(f"  {k} = {v!r}")


def main() -> int:
    p = lab.parser(__doc__.splitlines()[0])
    p.add_argument("--app", required=True)
    p.add_argument("--sourcetype", required=True)
    p.add_argument("--transform")
    args = p.parse_args()
    for name in (args.app, args.sourcetype, args.transform or "x"):
        if not NAME.fullmatch(name):
            raise SystemExit(f"refusing name {name!r}")
    service = lab.connect(args, lab.READ_TOKEN_ENV)
    if lab.whoami(service, lab.READ_TOKEN_ENV) is None:
        return 1
    lab.check_version(service)

    status, rows = lab.try_entries(service, f"apps/local/{args.app}")
    content = rows[0]["content"] if rows else {}
    hashy = {k: v for k, v in content.items() if "hash" in k.lower() or "checksum" in k.lower()}
    print(
        f"apps/local/{args.app}: {status}, version={content.get('version')!r}, "
        f"hash-like fields={hashy or 'none'}, keys={sorted(content)[:30]}"
    )
    st = args.sourcetype
    show(service, "props in app context", f"configs/conf-props/{st}", "nobody", args.app)
    show(service, "props in search app context", f"configs/conf-props/{st}", "nobody", "search")
    show(service, "props global (-/-)", f"configs/conf-props/{st}", "-", "-")
    show(service, "properties/props (global)", f"properties/props/{st}", "-", "-")
    if args.transform:
        tr = args.transform
        show(
            service,
            "transforms in app context",
            f"configs/conf-transforms/{tr}",
            "nobody",
            args.app,
        )
        show(service, "transforms global (-/-)", f"configs/conf-transforms/{tr}", "-", "-")
    # Which apps define the stanza at all: one entry per app/location where the API lists it.
    status, rows = lab.try_entries(
        service, "configs/conf-props", owner="-", app="-", search=f"name={st}"
    )
    owners = [r.get("acl", {}).get("app") for r in rows if r.get("name") == st]
    print(f"apps listing [{st}]: {status}, {owners}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
