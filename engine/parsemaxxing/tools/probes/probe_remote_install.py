"""Q12: can `apps/local` install a package that is not on the Splunk host's disk?

Builds a throwaway props-only add-on, serves exactly that one file over HTTP from this machine
for the length of the probe, and asks the node to install it from the URL through
`apps/local` (filename=true) and then `apps/appinstall`. For each attempt it records the
answer, whether the node fetched the file, the installed version, and any restart-required
message. On a node with the deployment server role (an HF-DS, Q14) it also compares the
client count before and after the install. Uninstalls the add-on at the end. Run it once per
candidate deploy role to find the narrowest capabilities (R8).
Only on lab nodes (--lab-write); never prints the token.
Run: PMX_LAB_DEPLOY_TOKEN=... python -m parsemaxxing.tools.probes.probe_remote_install \\
       --host <node> --lab-write --serve-bind <this machine's lab address> --serve-port 8765
"""

import http.server
import sys
import threading
from functools import partial

from splunklib.binding import HTTPError

from parsemaxxing.tools.probes import lab

APP = "TA-parsemaxxing-acme-remote__test_probe"
PROPS = "[pmx_probe_remote__test_probe]\nSHOULD_LINEMERGE = false\n"


class OneFile(http.server.BaseHTTPRequestHandler):
    """Serves one package at one path; every other request gets 404. Counts fetches."""

    def __init__(self, *a, path: str, data: bytes, hits: list, **kw):
        self.pkg_path, self.data, self.hits = path, data, hits
        super().__init__(*a, **kw)

    def do_GET(self) -> None:
        if self.path != self.pkg_path:
            self.send_error(404)
            return
        self.hits.append(1)
        self.send_response(200)
        self.send_header("Content-Type", "application/gzip")
        self.send_header("Content-Length", str(len(self.data)))
        self.end_headers()
        self.wfile.write(self.data)

    def log_message(self, *args) -> None:  # keep the client address out of the output
        return


def restart_messages(service) -> list[str]:
    _, rows = lab.try_entries(service, "messages")
    return [r.get("name", "") for r in rows if "restart" in str(r).lower()]


def ds_clients(service) -> int | None:
    status, rows = lab.try_entries(service, "deployment/server/clients")
    return len(rows) if status == "ok" else None


def attempt(service, label: str, path: str, url: str, hits: list) -> bool:
    before = len(hits)
    try:
        service.post(path, name=url, filename=True, update=True)
        result = "ok"
    except HTTPError as e:
        result = lab.http_error(e)
    status, rows = lab.try_entries(service, f"apps/local/{APP}")
    version = rows[0]["content"].get("version") if rows else None
    print(
        f"{label}: {result}; fetched={len(hits) - before}; installed={status == 'ok'} "
        f"version={version!r}; restart messages={restart_messages(service)}"
    )
    return status == "ok"


def main() -> int:
    p = lab.parser(__doc__.splitlines()[0], write=True)
    p.add_argument("--serve-bind", required=True, help="address of this machine on the lab net")
    p.add_argument("--serve-port", type=int, default=8765)
    args = p.parse_args()
    lab.require_lab_write(args)
    service = lab.connect(args, lab.DEPLOY_TOKEN_ENV)
    me = lab.whoami(service, lab.DEPLOY_TOKEN_ENV)
    if me is None:
        return 1
    lab.check_version(service)
    print(f"deploy token capabilities: {sorted(me.get('capabilities', []))}")

    data = lab.build_tgz(APP, lab.probe_files("0.0.1", {"default/props.conf": PROPS}))
    path = f"/{APP}-{lab.sha256_hex(data)[:12]}.tgz"
    hits: list = []
    handler = partial(OneFile, path=path, data=data, hits=hits)
    server = http.server.ThreadingHTTPServer((args.serve_bind, args.serve_port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://{args.serve_bind}:{args.serve_port}{path}"
    clients_before = ds_clients(service)
    installed = False
    try:
        installed |= attempt(service, "apps/local from URL", "apps/local", url, hits)
        if installed:
            lab.uninstall(service, APP)
            installed = False
        installed |= attempt(service, "apps/appinstall from URL", "apps/appinstall", url, hits)
        if clients_before is not None:
            print(f"deployment server clients before={clients_before} after={ds_clients(service)}")
    finally:
        server.shutdown()
        if installed:
            lab.uninstall(service, APP)
    print("upload (multipart) is not probed over REST: record Splunk Web upload by hand if needed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
