"""Prepare the bundled Splunk for Parsemaxxing. Runs INSIDE the splunk container (scripts/up.sh
pipes it to the container's python3), against https://127.0.0.1:8089, as admin, using the
SPLUNK_PASSWORD the container already has. Port 8089 stays unpublished.

Idempotent. Creates the test index, the three no-inheritance roles and users from
docs/lab-findings.md (Q9), installs the CIM add-on from a package in /opt/parsemaxxing/lab if
it is not installed, points the CIM index macros at pmx_*, then replaces each service user's
tokens with one fresh token, valid 7 days (`make up` again renews them). Progress goes to stderr; the only stdout is KEY=VALUE token lines
for scripts/env_set.py, which writes them to .env without printing them.

Standard library only (the container's python3); the lab's self-signed certificate is accepted
for this loopback connection only.
"""

import base64
import glob
import http.client
import json
import os
import re
import secrets
import ssl
import string
import sys
import time
import urllib.parse

INDEX = os.environ.get("PMX_TEST_INDEX", "pmx_test")
# `make up` mints new tokens each time; a short life limits a leaked deploy token (T7.4).
TOKEN_LIFETIME = "+7d"  # nosec B105 - a duration, not a secret
CIM_APP = "Splunk_SA_CIM"
CIM_MODELS = (
    "Authentication",
    "Network_Traffic",
    "Web",
)  # engine/parsemaxxing/cim_spec ROOT
# list_all_objects: read configs/conf-* (collision checks, effective props, _reload). Roles made
# in Splunk Web inherit it from authorize.conf [default]; roles made here must name it.
ROLES = {
    # Search only pmx_* and _internal (agents' searches and the Validator). Agents still cannot
    # read config: the search guard refuses `| rest`.
    "parsemaxxing_search": {
        "capabilities": ["list_all_objects", "search"],
        "srchIndexesAllowed": ["pmx_*", "_internal"],
        "srchIndexesDefault": ["pmx_*"],
    },
    # Install apps and ingest: the final deploy role from lab-findings Q9.
    "parsemaxxing_deploy": {
        "capabilities": [
            "admin_all_objects",
            "edit_tcp",
            "install_apps",
            "list_all_objects",
        ],
        "srchIndexesAllowed": ["pmx_*"],
        "srchIndexesDefault": ["pmx_*"],
    },
    # Read-only (the planned drift pipeline adds a search filter).
    "parsemaxxing_drift": {
        "capabilities": ["search"],
        "srchIndexesAllowed": ["pmx_*"],
        "srchIndexesDefault": ["pmx_*"],
    },
}
TOKEN_ENV = {
    "parsemaxxing_search": "SPLUNK_SEARCH_TOKEN",
    "parsemaxxing_deploy": "SPLUNK_DEPLOY_TOKEN",
    "parsemaxxing_drift": "SPLUNK_DRIFT_TOKEN",
}

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE  # loopback to this container's own splunkd only
AUTH = (
    "Basic "
    + base64.b64encode(("admin:" + os.environ["SPLUNK_PASSWORD"]).encode()).decode()
)


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def call(method, path, data=None):
    """(status, parsed JSON or None). Never raises on HTTP errors; the caller decides."""
    body = (
        urllib.parse.urlencode(data or {}, doseq=True).encode()
        if data is not None
        else None
    )
    sep = "&" if "?" in path else "?"
    headers = {"Authorization": AUTH}
    if body is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    # http.client speaks only HTTP(S) to this one host: no other scheme can be reached.
    # The context is explicit (unverified on purpose: loopback to this container's splunkd).
    # nosemgrep: python.lang.security.audit.httpsconnection-detected.httpsconnection-detected
    conn = http.client.HTTPSConnection("127.0.0.1", 8089, timeout=60, context=CTX)
    try:
        conn.request(
            method, path + sep + "output_mode=json", body=body, headers=headers
        )
        r = conn.getresponse()
        raw = r.read()
        if r.status >= 300:
            return r.status, None
        return r.status, (json.loads(raw) if raw else None)
    finally:
        conn.close()


def must(status, what):
    if status >= 300:
        log(f"FAILED: {what} (HTTP {status})")
        sys.exit(1)


def wait_ready(limit=600):
    start = time.time()
    while time.time() - start < limit:
        try:
            if call("GET", "/services/server/info")[0] == 200:
                return
        except OSError:
            pass
        time.sleep(5)
    log("FAILED: splunkd did not answer on 8089")
    sys.exit(1)


def wait_tokens(limit=300):
    """Tokens live in the KV store, which starts after splunkd answers: 503 until it is ready."""
    start = time.time()
    while time.time() - start < limit:
        try:
            if call("GET", "/services/authorization/tokens?count=1")[0] != 503:
                return
        except OSError:
            pass
        time.sleep(5)
    log("FAILED: the KV store is not ready, so tokens cannot be created (HTTP 503)")
    sys.exit(1)


def password():
    alphabet = string.ascii_letters + string.digits
    return "".join(
        secrets.choice(alphabet) for _ in range(40)
    )  # never kept: tokens authenticate


def main():
    if not re.fullmatch(r"pmx_[a-z0-9_-]{1,60}", INDEX):  # only pmx_ test indexes, ever
        log("FAILED: PARSEMAXXING_TEST_INDEX must look like pmx_<name>")
        sys.exit(1)
    wait_ready()
    must(
        call("POST", "/services/admin/token-auth/tokens_auth", {"disabled": "false"})[
            0
        ],
        "enable token authentication",
    )
    log("token authentication: enabled")

    if call("GET", "/services/data/indexes/" + INDEX)[0] == 404:
        # A size cap, not an age limit: sample events carry historical timestamps (Q9).
        must(
            call(
                "POST",
                "/services/data/indexes",
                {"name": INDEX, "maxTotalDataSizeMB": "2000"},
            )[0],
            "create index " + INDEX,
        )
        log(f"index {INDEX}: created")
    else:
        log(f"index {INDEX}: exists")

    for role, spec in ROLES.items():
        exists = call("GET", "/services/authorization/roles/" + role)[0] == 200
        data = dict(spec, imported_roles=[""] if exists else [])
        path = "/services/authorization/roles" + ("/" + role if exists else "")
        if not exists:
            data["name"] = role
        must(call("POST", path, data)[0], "role " + role)
        log("role {}: {}".format(role, "updated" if exists else "created"))

    for user in ROLES:
        if call("GET", "/services/authentication/users/" + user)[0] == 404:
            must(
                call(
                    "POST",
                    "/services/authentication/users",
                    {"name": user, "password": password(), "roles": user},
                )[0],
                "user " + user,
            )
            log(f"user {user}: created")
        else:
            must(
                call("POST", "/services/authentication/users/" + user, {"roles": user})[
                    0
                ],
                "user " + user,
            )
            log(f"user {user}: exists, role set")

    if call("GET", "/services/apps/local/" + CIM_APP)[0] == 404:
        found = glob.glob("/opt/parsemaxxing/lab/splunk-common-information-model-*.tgz")
        found += glob.glob("/opt/parsemaxxing/lab/Splunk_SA_CIM*.tgz")
        if len(found) != 1 or os.path.islink(found[0]):
            log(
                "FAILED: the CIM add-on is not installed; put exactly one CIM package "
                "(a regular file, not a link) in lab/ (see lab/README.md)"
            )
            sys.exit(2)
        must(
            call(
                "POST", "/services/apps/local", {"name": found[0], "filename": "true"}
            )[0],
            "install the CIM add-on",
        )
        log(
            f"CIM add-on: installed from lab/{os.path.basename(found[0])}; restarting splunkd"
        )
        call("POST", "/services/server/control/restart")
        time.sleep(20)
        wait_ready()
    status, app = call("GET", "/services/apps/local/" + CIM_APP)
    must(status, "read the CIM add-on")
    version = (
        ((app or {}).get("entry") or [{}])[0].get("content", {}).get("version", "?")
    )
    log(f"CIM add-on: version {version} (Parsemaxxing's checks are pinned to 8.7.0)")
    for model in CIM_MODELS:
        macro = f"cim_{model}_indexes"
        path = f"/servicesNS/nobody/{CIM_APP}/admin/macros/{macro}"
        must(call("POST", path, {"definition": "(index=pmx_*)"})[0], "macro " + macro)
    log("CIM index macros: (index=pmx_*) for {}".format(", ".join(CIM_MODELS)))

    wait_tokens()
    # One fresh token per service user; earlier ones are deleted, so a rebuilt .env never
    # leaves a valid old token behind.
    lines = []
    for user, key in TOKEN_ENV.items():
        status, listing = call(
            "GET", f"/services/authorization/tokens?username={user}&count=0"
        )
        must(status, "list tokens of " + user)
        for entry in (listing or {}).get("entry", []):
            claims = (entry.get("content") or {}).get("claims") or {}
            if claims.get("sub") != user:  # never touch another account's token
                continue
            path = "/services/authorization/tokens/{}?id={}".format(
                user, urllib.parse.quote(entry["name"])
            )
            must(call("DELETE", path)[0], "delete an old token of " + user)
        status, made = call(
            "POST",
            "/services/authorization/tokens",
            {"name": user, "audience": "parsemaxxing", "expires_on": TOKEN_LIFETIME},
        )
        must(status, "token for " + user)
        lines.append("{}={}".format(key, made["entry"][0]["content"]["token"]))
        log(f"token for {user}: created")
    sys.stdout.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
