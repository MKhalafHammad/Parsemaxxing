"""Q16: is the candidate parsemaxxing_read role enough, and no more than enough?

Runs, with the read token only, every read the read account needs (discovery tstats, samples,
_internal parser warnings for one sourcetype, fieldsummary, conf-props, apps/local, datamodel
listing) and the negative checks (an index outside the allowlist returns nothing, no write
capability is held). Prints pass/fail lines and counts; never raw events. Writes nothing.
Run: PMX_LAB_READ_TOKEN=... python -m parsemaxxing.tools.probes.probe_read_role \\
       --host <sh> --index <allowlisted index> --other-index <index the role must not see> \\
       --sourcetype <sourcetype>
"""

import re
import sys

from parsemaxxing.tools.probes import lab

NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:-]{0,79}")
WRITE_CAPS = {
    "admin_all_objects",
    "install_apps",
    "edit_tcp",
    "edit_token_http",
    "indexes_edit",
    "delete_by_keyword",
    "can_delete",
    "edit_roles",
    "edit_user",
    "edit_deployment_server",
    "rest_apps_management",
}
PARSER_COMPONENTS = "(LineBreakingProcessor DateParserVerbose AggregatorMiningProcessor)"


def checks(index: str, other: str, sourcetype: str) -> list[tuple[str, str]]:
    """(label, SPL) for every read the account needs; names validated first."""
    for name in (index, other, sourcetype):
        if not NAME.fullmatch(name):
            raise ValueError(f"refusing name {name!r}")
    base = f'index="{index}" sourcetype="{sourcetype}"'
    return [
        ("tstats volume", f"| tstats count where {base} by host span=1d"),
        ("samples", f"search {base} | head 5 | eval l=len(_raw) | table l"),
        (
            "time vs indextime",
            f"search {base} | head 100 | eval d=_indextime-_time | stats avg(d) max(d)",
        ),
        (
            "fieldsummary",
            f"search {base} | head 1000 | fieldsummary maxvals=5 "
            "| table field count distinct_count",
        ),
        (
            "parser warnings",
            f"search index=_internal sourcetype=splunkd log_level=WARN "
            f'component IN {PARSER_COMPONENTS} "{sourcetype}" | stats count by component',
        ),
        (
            "_internal other components (search filter check)",
            "search index=_internal "
            f"sourcetype=splunkd NOT component IN {PARSER_COMPONENTS} | stats count",
        ),
        ("outside allowlist (must be 0)", f'| tstats count where index="{other}"'),
    ]


def main() -> int:
    p = lab.parser(__doc__.splitlines()[0])
    p.add_argument("--index", required=True)
    p.add_argument("--other-index", required=True)
    p.add_argument("--sourcetype", required=True)
    args = p.parse_args()
    service = lab.connect(args, lab.READ_TOKEN_ENV)
    me = lab.whoami(service, lab.READ_TOKEN_ENV)
    if me is None:
        return 1
    lab.check_version(service)
    caps = set(me.get("capabilities", []))
    held = sorted(caps & WRITE_CAPS)
    print(f"capabilities ({len(caps)}): {sorted(caps)}")
    print(f"write capabilities held: {held or 'none'} ({'FAIL' if held else 'good'})")
    ok = not held
    for label, spl in checks(args.index, args.other_index, args.sourcetype):
        status, rows = lab.try_search(service, spl, earliest="-7d")
        counts = [r.get("count") for r in rows if "count" in r][:5]
        print(f"{label}: {status}, rows={len(rows)} counts={counts}")
        if label.startswith("outside"):
            leaked = any(int(c or 0) for c in counts)
            print(f"  outside allowlist visible: {leaked} ({'FAIL' if leaked else 'good'})")
            ok &= not leaked
    for path in ("configs/conf-props", "apps/local", "datamodel/model", "data/indexes"):
        status, rows = lab.try_entries(service, path)
        print(f"REST {path}: {status}, entries={len(rows)}")
    status, _ = lab.try_search(service, "| rest /services/server/info | table version")
    print(f"| rest from search: {status} (records whether the role can call rest from SPL)")
    print(f"read role probe: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
