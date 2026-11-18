"""Q20: header-defined formats (W3C/IIS, CSV): search-time DELIMS/FIELDS vs INDEXED_EXTRACTIONS.

Installs one throwaway add-on with four sourcetypes (W3C and CSV, each once with search-time
DELIMS/FIELDS and once with INDEXED_EXTRACTIONS), sends a synthetic file of each through
receivers/simple (and, with --oneshot, through data/inputs/oneshot from the packages folder,
since structured extraction may only run on file inputs), then counts per sourcetype: events,
header lines indexed as events, events with the URI field, indexed-field hits (tstats) and the
events an eventtype that excludes header lines keeps (the CIM path without nullQueue).
Only on lab nodes (--lab-write). Ingests only into a pmx_ index. Never prints tokens.
Run: PMX_LAB_DEPLOY_TOKEN=... PMX_LAB_READ_TOKEN=... PARSEMAXXING_PACKAGES_DIR=... \\
     python -m parsemaxxing.tools.probes.probe_formats --host <sandbox> --lab-write \\
       --index pmx_test [--oneshot]
"""

import os
import sys

from splunklib.binding import HTTPError

from parsemaxxing.tools.probes import lab
from parsemaxxing.tools.probes.probe_install import packages_dir

APP = "TA-parsemaxxing-acme-formats__test_probe"
FIELDS = "date,time,c_ip,cs_method,cs_uri_stem,sc_status"
W3C = """#Software: Acme Web Server 1.0
#Version: 1.0
#Date: 2026-01-02 03:04:05
#Fields: date time c-ip cs-method cs-uri-stem sc-status
2026-01-02 03:04:05 192.0.2.10 GET /index.html 200
2026-01-02 03:04:06 192.0.2.11 GET /login 302
2026-01-02 03:04:07 198.51.100.7 POST /login 200
"""
CSV = (
    FIELDS
    + "\n"
    + "\n".join(line.replace(" ", ",") for line in W3C.splitlines() if not line.startswith("#"))
    + "\n"
)
EXPECTED_EVENTS = 3
# sourcetype -> (sample, header exclusion terms, props body)
TIME = "TIME_FORMAT = %Y-%m-%d %H:%M:%S\nMAX_TIMESTAMP_LOOKAHEAD = 19\nTZ = UTC\n"
CASES = {
    "pmx_probe_w3cd__test_probe": (
        W3C,
        ['"#Fields:"', '"#Software:"', '"#Version:"', '"#Date:"'],
        "REPORT-f = pmx_probe_w3c_fields\n" + TIME,
    ),
    "pmx_probe_w3cx__test_probe": (W3C, ['"#Fields:"'], "INDEXED_EXTRACTIONS = w3c\n" + TIME),
    "pmx_probe_csvd__test_probe": (
        CSV,
        [f'"{FIELDS}"'],
        "REPORT-f = pmx_probe_csv_fields\nTIME_FORMAT = %Y-%m-%d,%H:%M:%S\nTZ = UTC\n",
    ),
    "pmx_probe_csvx__test_probe": (
        CSV,
        [f'"{FIELDS}"'],
        "INDEXED_EXTRACTIONS = csv\nTIMESTAMP_FIELDS = date,time\nTZ = UTC\n",
    ),
}
TRANSFORMS = f"""[pmx_probe_w3c_fields]
DELIMS = " "
FIELDS = {FIELDS}

[pmx_probe_csv_fields]
DELIMS = ","
FIELDS = {FIELDS}
"""


def package_files() -> dict[str, str]:
    props, eventtypes = [], []
    for st, (_, exclude, body) in CASES.items():
        props.append(f"[{st}]\nSHOULD_LINEMERGE = false\nLINE_BREAKER = ([\\r\\n]+)\n{body}")
        nots = " ".join(f"NOT {t}" for t in exclude)
        eventtypes.append(f"[{st}_events]\nsearch = sourcetype={st} {nots}\n")
    return lab.probe_files(
        "0.0.1",
        {
            "default/props.conf": "\n".join(props),
            "default/transforms.conf": TRANSFORMS,
            "default/eventtypes.conf": "\n".join(eventtypes),
        },
    )


def measure(search, index: str, st: str, source: str, label: str) -> None:
    where = f'index={index} sourcetype={st} source="{source}"'
    total = lab.wait_count(search, where)
    q = {
        "header lines as events": f'search {where} ("#*" OR "{FIELDS}") | stats count',
        "events with cs_uri_stem": f"search {where} | stats count(cs_uri_stem) as count",
        "indexed cs_uri_stem (tstats)": f"| tstats count where {where} cs_uri_stem=*",
        "kept by header-excluding eventtype": f"search {where} eventtype={st}_events | stats count",
    }
    parts = [f"events={total} (expect {EXPECTED_EVENTS})"]
    for name, spl in q.items():
        status, rows = lab.try_search(search, spl)
        parts.append(f"{name}={rows[0].get('count') if rows else status}")
    print(f"{st} via {label}: " + ", ".join(parts))


def main() -> int:
    p = lab.parser(__doc__.splitlines()[0], write=True)
    p.add_argument("--index", required=True)
    p.add_argument("--oneshot", action="store_true", help="also ingest via data/inputs/oneshot")
    args = p.parse_args()
    lab.require_lab_write(args)
    index = lab.require_pmx_index(args.index)
    deploy = lab.connect(args, lab.DEPLOY_TOKEN_ENV)
    search = lab.connect(args, lab.READ_TOKEN_ENV)
    if (
        lab.whoami(deploy, lab.DEPLOY_TOKEN_ENV) is None
        or lab.whoami(search, lab.READ_TOKEN_ENV) is None
    ):
        return 1
    lab.check_version(deploy)
    dest = packages_dir()
    data = lab.build_tgz(APP, package_files())
    pkg = lab.write_package(dest, f"{APP}-{lab.sha256_hex(data)[:12]}.tgz", data)
    written = [pkg]
    try:
        result = lab.install_path(deploy, pkg)
        print(f"install: {result}")
        if result != "ok":
            return 1
        for st, (sample, _, _) in CASES.items():
            measure(search, index, st, lab.ingest(deploy, index, st, sample), "receivers/simple")
            if args.oneshot:
                name = f"{st}-{os.urandom(4).hex()}.log"
                path = lab.write_package(dest, name, sample.encode())
                written.append(path)
                try:
                    deploy.post("data/inputs/oneshot", name=path, index=index, sourcetype=st)
                    measure(search, index, st, path, "oneshot")
                except HTTPError as e:
                    print(f"{st} via oneshot: {lab.http_error(e)}")
    finally:
        lab.uninstall(deploy, APP)
        for path in written:
            os.unlink(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
