"""Q23: which app name and placement make an overlay's props win over another app's settings
for the same sourcetype stanza?

On a standalone sandbox (or an HF, with --search-host pointing at a search head that sees the
pmx_ index): for every simulated vendor app name x overlay app name x placement (overlay
settings in default/ or local/), it installs both throwaway add-ons, ingests one event and
records which TZ won at index time (from _time) and which EVAL won at search time, plus the
effective value read back over REST. Uninstalls both after each round.
Only on lab nodes (--lab-write). Ingests only into a pmx_ index. Never prints tokens.
Run: PMX_LAB_DEPLOY_TOKEN=... PMX_LAB_READ_TOKEN=... PARSEMAXXING_PACKAGES_DIR=... \\
     python -m parsemaxxing.tools.probes.probe_overlay --host <node> --lab-write \\
       --index pmx_test [--vendor-name Splunk_TA_acmeprobe__test_probe ...] \\
       [--overlay-name TA-parsemaxxing-overlay-acme-probe__test_probe ...]
"""

import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from parsemaxxing.tools.probes import lab
from parsemaxxing.tools.probes.probe_install import packages_dir

SOURCETYPE = "pmx_probe_ovl__test_probe"
STAMP = "2026-01-02 03:04:05"
VENDORS = ["Splunk_TA_acmeprobe__test_probe", "zz_acmeprobe__test_probe"]
OVERLAYS = ["TA-parsemaxxing-overlay-acme-probe__test_probe"]


def props(tz: str, winner: str) -> str:
    return (
        f"[{SOURCETYPE}]\nSHOULD_LINEMERGE = false\nLINE_BREAKER = ([\\r\\n]+)\n"
        f"TIME_PREFIX = ts=\nTIME_FORMAT = %Y-%m-%d %H:%M:%S\nMAX_TIMESTAMP_LOOKAHEAD = 19\n"
        f'TZ = {tz}\nEVAL-pmx_winner = "{winner}"\n'
    )


def epoch(tz: str) -> int:
    return int(datetime.fromisoformat(STAMP).replace(tzinfo=ZoneInfo(tz)).timestamp())


WHO = {epoch("UTC"): "vendor", epoch("Pacific/Chatham"): "overlay"}


def round_trip(deploy, search, args, dest, vendor: str, overlay: str, placement: str) -> None:
    vpkg = lab.build_tgz(
        vendor, lab.probe_files("1.0.0", {"default/props.conf": props("UTC", "vendor")})
    )
    opkg = lab.build_tgz(
        overlay,
        lab.probe_files("1.0.0", {f"{placement}/props.conf": props("Pacific/Chatham", "overlay")}),
    )
    paths = [
        lab.write_package(dest, f"{a}-{lab.sha256_hex(d)[:12]}.tgz", d)
        for a, d in ((vendor, vpkg), (overlay, opkg))
    ]
    try:
        results = [lab.install_path(deploy, p) for p in paths]
        if results != ["ok", "ok"]:
            print(f"{vendor} + {overlay} ({placement}): install {results}")
            return
        source = lab.ingest(deploy, args.index, SOURCETYPE, f"probe ts={STAMP}")
        where = f"index={args.index} sourcetype={SOURCETYPE} source={source}"
        lab.wait_count(search, where)
        rows = lab.search(search, f"search {where} | eval t=floor(_time) | table t pmx_winner")
        t = int(rows[0]["t"]) if rows else None
        st, eff = lab.try_entries(deploy, f"configs/conf-props/{SOURCETYPE}", owner="-", app="-")
        c = eff[0]["content"] if eff else {}
        print(
            f"{vendor} + {overlay} ({placement}): index-time TZ winner={WHO.get(t, t)}, "
            f"search-time EVAL winner={rows[0].get('pmx_winner') if rows else None}, "
            f"REST global TZ={c.get('TZ')!r} EVAL={c.get('EVAL-pmx_winner')!r} ({st})"
        )
    finally:
        lab.uninstall(deploy, overlay)
        lab.uninstall(deploy, vendor)
        for p in paths:
            os.unlink(p)


def main() -> int:
    p = lab.parser(__doc__.splitlines()[0], write=True)
    p.add_argument("--index", required=True, help="the shared pmx_ test index")
    p.add_argument("--search-host", help="search head that sees the index (default: --host)")
    p.add_argument("--vendor-name", action="append")
    p.add_argument("--overlay-name", action="append")
    args = p.parse_args()
    lab.require_lab_write(args)
    lab.require_pmx_index(args.index)
    vendors = [lab.require_probe_app(v) for v in args.vendor_name or VENDORS]
    overlays = [lab.require_probe_app(o) for o in args.overlay_name or OVERLAYS]
    deploy = lab.connect(args, lab.DEPLOY_TOKEN_ENV)
    search = lab.connect(args, lab.READ_TOKEN_ENV, host=args.search_host)
    if (
        lab.whoami(deploy, lab.DEPLOY_TOKEN_ENV) is None
        or lab.whoami(search, lab.READ_TOKEN_ENV) is None
    ):
        return 1
    lab.check_version(deploy)
    dest = packages_dir()
    for vendor in vendors:
        for overlay in overlays:
            for placement in ("default", "local"):
                round_trip(deploy, search, args, dest, vendor, overlay, placement)
    return 0


if __name__ == "__main__":
    sys.exit(main())
