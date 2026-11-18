"""Q21 and Q22: what `datamodel/model` returns compared with the CIM package's own JSON, and
whether the read account sees the exact installed Splunk_SA_CIM version.

With the read token: reads apps/local/Splunk_SA_CIM (version), checks it against the D10
compatibility table, then for each data model summarises the REST answer (datasets, fields,
expected_values, constraints, child datasets) with a hash of that summary. With
--package-dir pointing at an extracted `default/data/models/` folder of the same CIM version
(the owner's own download, never committed) it summarises each package JSON the same way and
reports whether the hashes match. Writes nothing.
Run: PMX_LAB_READ_TOKEN=... python -m parsemaxxing.tools.probes.probe_cim --host <sh> \\
       [--package-dir /path/to/Splunk_SA_CIM/default/data/models] [--model Authentication]
"""

import json
import sys
from pathlib import Path

from parsemaxxing.tools.probes import lab

MAX_MODEL_BYTES = 4 * 1024 * 1024


def summarize_model(model: dict) -> dict:
    """A comparable shape of one CIM model: per dataset its parent, constraint and fields.

    Reads both the package layout and the REST `eai:data` layout (same JSON in both, if Q21
    confirms it); differences show up as different summaries, not as errors.
    """
    datasets = {}
    for obj in model.get("objects", []):
        constraints = [c.get("search", "") for c in obj.get("constraints", [])]
        fields = {}
        calc_fields = [f for c in obj.get("calculations", []) for f in c.get("outputFields", [])]
        for f in obj.get("fields", []) + calc_fields:
            comment = f.get("comment") if isinstance(f.get("comment"), dict) else {}
            fields[f.get("fieldName")] = {
                "type": f.get("type"),
                # CIM marks required fields as recommended in the field comment.
                "recommended": bool(comment.get("recommended") or f.get("required")),
                "expected": sorted(map(str, comment.get("expected_values") or [])),
            }
        datasets[obj.get("objectName")] = {
            "parent": obj.get("parentName"),
            "constraints": constraints,
            "fields": fields,
        }
    return {"modelName": model.get("modelName"), "datasets": datasets}


def summary_hash(summary: dict) -> str:
    return lab.sha256_hex(json.dumps(summary, sort_keys=True).encode())[:16]


def describe(label: str, summary: dict) -> None:
    ds = summary["datasets"]
    n_fields = sum(len(d["fields"]) for d in ds.values())
    n_expected = sum(1 for d in ds.values() for f in d["fields"].values() if f["expected"])
    children = sum(1 for d in ds.values() if d["parent"] not in (None, "BaseEvent"))
    print(
        f"{label}: datasets={len(ds)} children={children} fields={n_fields} "
        f"with_expected_values={n_expected} hash={summary_hash(summary)}"
    )


def load_package(path: Path) -> dict:
    if path.is_symlink() or path.stat().st_size > MAX_MODEL_BYTES:
        raise ValueError(f"refusing {path.name}: symlink or larger than {MAX_MODEL_BYTES} bytes")
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    p = lab.parser(__doc__.splitlines()[0])
    p.add_argument("--package-dir", type=Path)
    p.add_argument("--model", action="append", help="limit to these models (repeatable)")
    args = p.parse_args()
    service = lab.connect(args, lab.READ_TOKEN_ENV)
    if lab.whoami(service, lab.READ_TOKEN_ENV) is None:
        return 1
    splunk = lab.check_version(service)
    status, rows = lab.try_entries(service, "apps/local/Splunk_SA_CIM")
    cim = str(rows[0]["content"].get("version", "")) if rows else ""
    print(
        f"apps/local/Splunk_SA_CIM: {status}, version={cim!r} "
        f"(x.y.z: {len(lab.version_tuple(cim)) == 3})"
    )
    minimum = lab.cim_minimum(splunk)
    print(f"CIM minimum for {splunk}: {minimum}; installed ok: {lab.cim_ok(splunk, cim)}")

    status, rows = lab.try_entries(service, "datamodel/model", owner="nobody", app="Splunk_SA_CIM")
    print(f"datamodel/model: {status}, models={len(rows)}, keys={lab.keys_of(rows)[:20]}")
    mismatches = 0
    for r in rows:
        name = r.get("name", "")
        if args.model and name not in args.model:
            continue
        raw = r.get("content", {}).get("eai:data") or r.get("content", {}).get("description")
        try:
            rest = summarize_model(json.loads(raw) if isinstance(raw, str) else raw or {})
        except (ValueError, TypeError) as e:
            print(f"{name}: REST definition not JSON ({type(e).__name__})")
            continue
        describe(f"{name} REST", rest)
        if args.package_dir:
            pkg_file = args.package_dir / f"{name}.json"
            if not pkg_file.is_file():
                print(f"{name}: not in package dir")
                continue
            pkg = summarize_model(load_package(pkg_file))
            describe(f"{name} package", pkg)
            same = summary_hash(pkg) == summary_hash(rest)
            mismatches += not same
            if not same:
                only_rest = sorted(set(rest["datasets"]) ^ set(pkg["datasets"]))
                print(f"  DIFFERENT; datasets in only one side: {only_rest}")
    print(f"cim probe: {mismatches} model(s) differ between REST and package")
    return 0


if __name__ == "__main__":
    sys.exit(main())
