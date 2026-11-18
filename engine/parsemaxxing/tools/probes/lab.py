"""Shared helpers for the Phase 11 lab probes (Q12 to Q24, docs/lab-findings.md).

Safety rules every v2 probe follows:
- Tokens come only from environment variables (never arguments: other users see `ps`), and
  are never printed; a rejected token is described by its shape only.
- TLS certificates are verified by default (system store or --ca-file). Only the explicit
  per-run flag --insecure-skip-tls-verify turns it off, and the probe says so on every run.
- Every REST call and search has a timeout; searches have a row cap.
- Probes that write (install a test add-on, ingest, push, map) refuse to run without --lab-write,
  touch only apps named `...__test_probe` and ingest only into a `pmx_` index.
- Hostnames, IPs and client names read from Splunk are printed as short hashes, never raw.
Never run in CI: nothing here is imported by the engine or the tests except the pure helpers.
"""

import argparse
import hashlib
import io
import json
import os
import re
import ssl
import tarfile
import time
from collections.abc import Iterable
from typing import Any

import splunklib.binding as binding
import splunklib.client as client
import splunklib.results as results
from splunklib.binding import AuthenticationError, HTTPError

from parsemaxxing.tools.probes.probe_splunk import require_pmx_index, token_shape

READ_TOKEN_ENV = "PMX_LAB_READ_TOKEN"  # noqa: S105  # nosec B105 - a variable name, not a secret
DEPLOY_TOKEN_ENV = "PMX_LAB_DEPLOY_TOKEN"  # noqa: S105  # nosec B105
MAX_ROWS = 200
# shortcut: kept here until environments/versions.py exists (Phase 12); move the table there.
MIN_SPLUNK = (10, 2)
CIM_MINIMUM = [((10, 7), (8, 5, 0)), ((10, 2), (6, 3, 0))]  # (from Splunk, minimum CIM)
MAX_RETENTION_SECS = 30 * 24 * 3600
# A probe app: test identity suffix, Splunk app-name characters only.
PROBE_APP = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,80}__test_probe")
PROBE_SOURCETYPE = re.compile(r"pmx_probe_[a-z0-9_]{1,40}__test_probe")


def parser(description: str, write: bool = False) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=description)
    p.add_argument("--host", default=os.environ.get("PMX_LAB_HOST", ""), help="node to probe")
    p.add_argument("--port", type=int, default=int(os.environ.get("PMX_LAB_PORT", "8089")))
    p.add_argument("--ca-file", default=os.environ.get("PMX_LAB_CA_FILE"), help="CA bundle")
    p.add_argument(
        "--insecure-skip-tls-verify",
        action="store_true",
        help="this run only: do not verify the node's certificate (self-signed lab only)",
    )
    p.add_argument("--timeout", type=float, default=30.0, help="seconds per REST call")
    if write:
        p.add_argument(
            "--lab-write",
            action="store_true",
            help="required: confirms this node is a lab or sandbox node, never production",
        )
    return p


def tls_context(ca_file: str | None) -> ssl.SSLContext:
    ctx = ssl.create_default_context(cafile=ca_file)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx


def connect(args: argparse.Namespace, token_env: str, host: str | None = None) -> client.Service:
    host = host or args.host
    if not host:
        raise SystemExit("set --host or PMX_LAB_HOST")
    token = os.environ.get(token_env, "")
    if not token:
        raise SystemExit(f"set {token_env} in the environment (never on the command line)")
    verify = not args.insecure_skip_tls_verify
    if not verify:
        print("WARNING: TLS certificate verification is OFF for this run (flag given)")
    handler = binding.handler(
        timeout=args.timeout, verify=verify, context=tls_context(args.ca_file) if verify else None
    )
    service = client.connect(
        handler=handler,
        host=host,
        port=args.port,
        splunkToken=token,
        verify=verify,
        autologin=False,
    )
    return service


def require_lab_write(args: argparse.Namespace) -> None:
    if not getattr(args, "lab_write", False):
        raise SystemExit("this probe writes to the node: rerun with --lab-write on a lab node only")


def require_probe_app(name: str) -> str:
    if not PROBE_APP.fullmatch(name) or ".." in name:
        raise ValueError(f"refusing app name {name!r}: probe apps end with __test_probe")
    return name


def require_probe_sourcetype(name: str) -> str:
    if not PROBE_SOURCETYPE.fullmatch(name):
        raise ValueError(f"refusing sourcetype {name!r}: use pmx_probe_<x>__test_probe")
    return name


def anon(value: object) -> str:
    """A stable short label for a hostname, IP or client name, so output can be pasted."""
    return "h-" + hashlib.sha256(str(value).encode()).hexdigest()[:8]


def version_tuple(text: str) -> tuple[int, ...]:
    """'10.2.1' -> (10, 2, 1); trailing build text is ignored. Empty tuple if unparseable."""
    m = re.match(r"\s*(\d+(?:\.\d+)*)", text or "")
    return tuple(int(x) for x in m.group(1).split(".")) if m else ()


def splunk_supported(version: str) -> bool:
    return version_tuple(version)[:2] >= MIN_SPLUNK


def cim_minimum(splunk_version: str) -> tuple[int, ...] | None:
    v = version_tuple(splunk_version)[:2]
    for since, minimum in CIM_MINIMUM:
        if v >= since:
            return minimum
    return None


def cim_ok(splunk_version: str, cim_version: str) -> bool:
    minimum = cim_minimum(splunk_version)
    cim = version_tuple(cim_version)
    return minimum is not None and bool(cim) and cim >= minimum


def entries(service: client.Service, path: str, **query: Any) -> list[dict]:
    """GET a REST path as JSON and return its entries; HTTPError propagates."""
    body = service.get(path, output_mode="json", count=MAX_ROWS, **query).body.read()
    return json.loads(body).get("entry", [])


def try_entries(service: client.Service, path: str, **query: Any) -> tuple[str, list[dict]]:
    """Like entries(), but returns ('ok' | 'HTTP <status>' | 'auth refused', entries)."""
    try:
        return "ok", entries(service, path, **query)
    except AuthenticationError:
        return "auth refused", []
    except HTTPError as e:
        return f"HTTP {e.status}", []


def whoami(service: client.Service, token_env: str) -> dict | None:
    status, rows = try_entries(service, "authentication/current-context")
    if not rows:
        print(f"{token_env}: {status}. Token shape: {token_shape(os.environ.get(token_env, ''))}")
        return None
    content = rows[0]["content"]
    print(f"{token_env}: user={content.get('username')} roles={content.get('roles')}")
    return content


def server_version(service: client.Service) -> str:
    rows = entries(service, "server/info")
    return str(rows[0]["content"].get("version", "")) if rows else ""


def check_version(service: client.Service) -> str:
    version = server_version(service)
    if not splunk_supported(version):
        raise SystemExit(
            f"Splunk Enterprise {version} is not supported; Parsemaxxing supports 10.2 and later"
        )
    print(f"splunk version: {version}")
    return version


def search(service: client.Service, spl: str, earliest: str = "0", latest: str = "now") -> list:
    """Run one fixed probe search with a row cap; returns result dicts only."""
    stream = service.jobs.oneshot(
        spl, output_mode="json", earliest_time=earliest, latest_time=latest, count=MAX_ROWS
    )
    return [r for r in results.JSONResultsReader(stream) if isinstance(r, dict)]


def try_search(service: client.Service, spl: str, **kw: str) -> tuple[str, list]:
    try:
        return "ok", search(service, spl, **kw)
    except HTTPError as e:
        return f"HTTP {e.status}", []


def wait_count(service: client.Service, where: str, tries: int = 30) -> int:
    """Poll a tstats count until two polls match (as the Validator does)."""
    seen = -1
    for _ in range(tries):
        time.sleep(2)
        rows = search(service, f"| tstats count where {where}")
        now = int(rows[0].get("count", 0)) if rows else 0
        if now and now == seen:
            return now
        seen = now
    return max(seen, 0)


def build_tgz(app: str, files: dict[str, str]) -> bytes:
    """A probe add-on as .tgz bytes: regular files only, every path under <app>/."""
    require_probe_app(app)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for rel, text in sorted(files.items()):
            if rel.startswith("/") or ".." in rel.split("/") or "\\" in rel:
                raise ValueError(f"bad package path {rel!r}")
            data = text.encode()
            info = tarfile.TarInfo(f"{app}/{rel}")
            info.size, info.mode, info.mtime = len(data), 0o644, 0
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def write_package(dest: os.PathLike, name: str, data: bytes) -> str:
    """Write a package into the packages folder; O_EXCL/O_NOFOLLOW refuse planted files."""
    path = os.path.join(dest, name)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    os.fchmod(fd, 0o644)  # splunkd runs as another user and must read it
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return path


APP_CONF = """[install]
state = enabled

[ui]
is_visible = false
label = Parsemaxxing lab probe

[launcher]
version = {version}
description = Throwaway add-on for a Parsemaxxing lab probe.
"""
EXPORT_META = """[]
access = read : [ * ], write : [ admin ]
export = system
"""


def probe_files(version: str, extra: dict[str, str]) -> dict[str, str]:
    return {
        "default/app.conf": APP_CONF.format(version=version),
        "metadata/default.meta": EXPORT_META,
    } | extra


def install_path(service: client.Service, path: str) -> str:
    """Install or update from a path on the Splunk host. Returns 'ok' or the refusal."""
    try:
        service.post("apps/local", name=path, filename=True, update=True)
    except HTTPError as e:
        return http_error(e)
    return "ok"


def ingest(service: client.Service, index: str, sourcetype: str, body: str) -> str:
    """Post events through receivers/simple into a pmx_ index; returns the unique source."""
    source = f"parsemaxxing_probe_{os.urandom(4).hex()}"
    service.indexes[require_pmx_index(index)].submit(
        body, sourcetype=require_probe_sourcetype(sourcetype), source=source
    )
    return source


def uninstall(service: client.Service, app: str) -> None:
    try:
        service.delete(f"apps/local/{require_probe_app(app)}")
        print(f"cleanup: {app} uninstalled")
    except HTTPError as e:
        print(f"cleanup: uninstall of {app} refused HTTP {e.status}; remove it by hand")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def keys_of(rows: Iterable[dict]) -> list[str]:
    """Union of content keys across REST entries, without values (safe to print)."""
    seen: set[str] = set()
    for r in rows:
        seen |= set(r.get("content", {}))
    return sorted(seen)


IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
FQDN = re.compile(r"\b(?:[A-Za-z0-9-]{1,63}\.)+[A-Za-z]{2,63}\b")
KEYLIKE = re.compile(r"[A-Za-z0-9_\-.]{32,}")


def scrub(text: str, limit: int = 200) -> str:
    """Make a Splunk error message safe to paste: no IPs, host names or token-like strings."""
    text = KEYLIKE.sub("[redacted]", str(text))
    text = IPV4.sub(lambda m: lab_label(m.group()), text)
    text = FQDN.sub(lambda m: lab_label(m.group()), text)
    return text.replace("\n", " ")[:limit]


def lab_label(value: str) -> str:
    return "<" + anon(value) + ">"


def http_error(e: HTTPError) -> str:
    return scrub(str(e), 200)
