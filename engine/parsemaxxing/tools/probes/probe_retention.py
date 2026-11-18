"""Q24: how to remove one job's events from the sandbox's pmx_ test index without `delete`.

Read part (read token): the index's retention and size settings, bucket states (dbinspect),
and per sourcetype the event count and the _time / _indextime range, so the owner sees how
many events an age-based freeze would drop early (samples carry historical timestamps, which
conflicts with the Q9 size-only decision). With --roll (deploy token, --lab-write) it rolls the
hot buckets and re-reads the counts after --wait seconds, to show whether rolled buckets with
old _time freeze, and that other jobs' sourcetypes in the same index are affected the same way.
Never deletes anything itself; `splunk clean eventdata` stays a manual, maintenance-window step.
Run: PMX_LAB_READ_TOKEN=... python -m parsemaxxing.tools.probes.probe_retention \\
       --host <sandbox> --index pmx_test [--lab-write --roll --wait 120]
"""

import re
import sys
import time

from splunklib.binding import HTTPError

from parsemaxxing.tools.probes import lab

SETTINGS = (
    "frozenTimePeriodInSecs",
    "maxTotalDataSizeMB",
    "maxHotSpanSecs",
    "maxHotBuckets",
    "maxDataSize",
    "totalEventCount",
    "currentDBSizeMB",
    "coldToFrozenDir",
)


def retention_verdict(frozen_secs: object) -> str:
    try:
        secs = int(str(frozen_secs))
    except ValueError:
        return f"unreadable ({frozen_secs!r})"
    if secs > lab.MAX_RETENTION_SECS:
        return f"FAIL: {secs // 86400} days is over the 30-day maximum (design 7.19)"
    return f"ok: {secs // 86400} days"


def per_sourcetype(search, index: str) -> dict[str, tuple]:
    rows = lab.search(
        search,
        f"| tstats count min(_time) as t0 max(_time) as t1 "
        f"min(_indextime) as i0 where index={index} by sourcetype",
    )
    return {
        r["sourcetype"]: (int(r.get("count", 0)), r.get("t0"), r.get("t1"), r.get("i0"))
        for r in rows
    }


def show(search, index: str, frozen: int | None) -> dict[str, tuple]:
    counts = per_sourcetype(search, index)
    now = time.time()
    for st, (n, t0, _t1, i0) in sorted(counts.items())[:50]:
        old = ""
        if frozen and t0 is not None and re.fullmatch(r"[A-Za-z0-9_.:-]+", st):
            spl = f"| tstats count where index={index} sourcetype={st} _time<{int(now - frozen)}"
            rows = lab.search(search, spl)
            old = f", older than retention={rows[0].get('count') if rows else 0}"
        lag = int(float(i0) - float(t0)) if t0 is not None and i0 is not None else None
        print(f"  {st}: events={n}, first _time is {lag}s before first _indextime{old}")
    return counts


def main() -> int:
    p = lab.parser(__doc__.splitlines()[0], write=True)
    p.add_argument("--index", required=True)
    p.add_argument("--roll", action="store_true")
    p.add_argument("--wait", type=int, default=120)
    args = p.parse_args()
    index = lab.require_pmx_index(args.index)
    search = lab.connect(args, lab.READ_TOKEN_ENV)
    if lab.whoami(search, lab.READ_TOKEN_ENV) is None:
        return 1
    lab.check_version(search)
    status, rows = lab.try_entries(search, f"data/indexes/{index}")
    content = rows[0]["content"] if rows else {}
    print(f"data/indexes/{index}: {status}")
    for key in SETTINGS:
        print(f"  {key} = {content.get(key)!r}")
    frozen = content.get("frozenTimePeriodInSecs")
    print(f"retention: {retention_verdict(frozen)}")
    st, buckets = lab.try_search(search, f"| dbinspect index={index} | stats count by state")
    print(f"dbinspect: {st}, {[(b.get('state'), b.get('count')) for b in buckets]}")
    frozen_int = int(frozen) if str(frozen).isdigit() else None
    before = show(search, index, frozen_int)
    if not args.roll:
        return 0
    lab.require_lab_write(args)
    deploy = lab.connect(args, lab.DEPLOY_TOKEN_ENV)
    try:
        deploy.post(f"data/indexes/{index}/roll-hot-buckets")
        print("roll-hot-buckets: ok")
    except HTTPError as e:
        print(f"roll-hot-buckets: {lab.http_error(e)}")
        return 1
    time.sleep(max(0, min(args.wait, 3600)))
    after = show(search, index, frozen_int)
    for name in sorted(set(before) | set(after)):
        b, a = before.get(name, (0,))[0], after.get(name, (0,))[0]
        if a != b:
            print(f"  changed after roll: {name} {b} -> {a}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
