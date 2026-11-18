"""Q13 and Q14 delivery steps that REST might do: the SHC deployer push and the deployment
server mapping for heavy forwarders.

Subcommands (writes need --lab-write; only probe apps named `...__test_probe`):
  shc-calls   read-only: find the REST calls a CLI `splunk apply shcluster-bundle` made, from
              the deployer's splunkd_access log (run the CLI push once first, by hand)
  shc-push    POST apps/deploy on the deployer with a token. It pushes the deployer's whole
              staged bundle to the cluster, so it also needs --deployer-guid matching this
              deployer's server/info GUID (a lab deployer holding only probe apps)
  ds-map      on a DS for HFs: create a probe server class for one named client, map an app
              already staged in deployment-apps, reload; refuses a client that looks like a UF
  ds-unmap    remove the probe server class again
Run: PMX_LAB_DEPLOY_TOKEN=... python -m parsemaxxing.tools.probes.probe_delivery \\
       --host <deployer or DS> --lab-write <subcommand> ...
"""

import re
import sys

from splunklib.binding import HTTPError

from parsemaxxing.tools.probes import lab

SERVERCLASS = "pmx_probe_hf__test_probe"
MEMBER_URI = re.compile(r"https://[A-Za-z0-9.-]{1,253}:[0-9]{1,5}")


def looks_universal(content: dict) -> bool | None:
    """True if a deployment client entry says it is a universal forwarder, None if unknown.

    shortcut: the field names are guesses until probe_topology shows what 10.2/10.6 return.
    """
    text = " ".join(str(content.get(k, "")) for k in ("package", "packageType", "build"))
    if not text.strip():
        return None
    return "universal" in text.lower() or "splunkforwarder" in text.lower()


def shc_calls(service) -> None:
    spl = (
        'search index=_internal sourcetype=splunkd_access (uri_path="*/apps/deploy*" OR '
        'uri_path="*/shcluster/*") | stats count by method uri_path status'
    )
    status, rows = lab.try_search(service, spl, earliest="-24h")
    print(f"deployer access log: {status}")
    for r in rows:
        print(f"  {r.get('method')} {r.get('uri_path')} -> {r.get('status')} x{r.get('count')}")


def require_push_target(member: str, deployer_guid: str, actual_guid: str) -> None:
    """apps/deploy pushes the whole bundle, so the operator must name this exact deployer."""
    if not MEMBER_URI.fullmatch(member):
        raise SystemExit("refusing: --member must be https://<host>:<port>")
    if not actual_guid or deployer_guid != actual_guid:
        raise SystemExit("refusing: --deployer-guid does not match this deployer's server/info")


def shc_push(service, member: str, action: str, deployer_guid: str) -> None:
    require_push_target(member, deployer_guid, str(service.info.get("guid", "")))
    try:
        service.post("apps/deploy", target=member, action=action, advertising="true")
        print(f"apps/deploy action={action}: ok")
    except HTTPError as e:
        print(f"apps/deploy action={action}: {lab.http_error(e)}")
    status, rows = lab.try_entries(service, "shcluster/status")
    print(f"shcluster/status after push: {status}, entries={len(rows)}")


def ds_map(service, client_name: str, app: str) -> int:
    lab.require_probe_app(app)
    status, rows = lab.try_entries(service, "deployment/server/clients")
    match = [
        r
        for r in rows
        if client_name
        in (r.get("name"), r.get("content", {}).get("name"), r.get("content", {}).get("hostname"))
    ]
    if len(match) != 1:
        print(f"clients: {status}; {len(match)} match the given client: need exactly 1")
        return 1
    uf = looks_universal(match[0].get("content", {}))
    print(f"client {lab.anon(client_name)}: universal forwarder={uf}")
    if uf is not False:
        print("refusing: cannot prove this client is a heavy forwarder")
        return 1
    steps = [
        (
            "create server class",
            "deployment/server/serverclasses",
            {"name": SERVERCLASS, "whitelist.0": client_name},
        ),
        ("map app", f"deployment/server/applications/{app}", {"serverclass": SERVERCLASS}),
        ("reload", "deployment/server/config/_reload", {}),
    ]
    for label, path, body in steps:
        try:
            service.post(path, **body)
            print(f"{label}: ok")
        except HTTPError as e:
            print(f"{label}: {lab.http_error(e)}")
            return 1
    print("now check the HF: probe_readback --app <app> on it, and messages for restart")
    return 0


def main() -> int:
    p = lab.parser(__doc__.splitlines()[0], write=True)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("shc-calls")
    push = sub.add_parser("shc-push")
    push.add_argument("--member", required=True, help="https://<member>:8089")
    push.add_argument("--action", default="all", choices=["all", "lookups"])
    push.add_argument("--deployer-guid", required=True, help="server/info guid of the lab deployer")
    m = sub.add_parser("ds-map")
    m.add_argument("--client", required=True, help="deployment client name of one lab HF")
    m.add_argument("--app", required=True)
    sub.add_parser("ds-unmap")
    args = p.parse_args()
    if args.cmd != "shc-calls":  # the only read-only subcommand, run with the read token
        lab.require_lab_write(args)
    token_env = lab.READ_TOKEN_ENV if args.cmd == "shc-calls" else lab.DEPLOY_TOKEN_ENV
    service = lab.connect(args, token_env)
    me = lab.whoami(service, token_env)
    if me is None:
        return 1
    lab.check_version(service)
    print(f"token capabilities: {sorted(me.get('capabilities', []))}")
    if args.cmd == "shc-calls":
        shc_calls(service)
    elif args.cmd == "shc-push":
        shc_push(service, args.member, args.action, args.deployer_guid)
    elif args.cmd == "ds-map":
        return ds_map(service, args.client, args.app)
    else:
        try:
            service.delete(f"deployment/server/serverclasses/{SERVERCLASS}")
            print("probe server class removed")
        except HTTPError as e:
            print(f"remove server class: {lab.http_error(e)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
