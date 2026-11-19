"""docker-compose.yml and the Dockerfiles keep the container baseline (security-baseline DK-1 to
DK-7, SC-2): read from the files, so no Docker daemon is needed."""

import ipaddress
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
SERVICES = COMPOSE["services"]
# Splunk's image needs sudo inside (DK-2 residual risk); isolated by network instead.
UNHARDENED = {"splunk"}
DIGEST = re.compile(r"^[a-z0-9][a-z0-9./_-]*:[A-Za-z0-9._-]+@sha256:[0-9a-f]{64}$")


def networks(service: str) -> set[str]:
    return set(SERVICES[service].get("networks") or [])


def test_hardening_and_limits_on_every_service() -> None:
    for name, svc in SERVICES.items():
        limits = svc["deploy"]["resources"]["limits"]
        assert {"cpus", "memory", "pids"} <= set(limits), name
        assert "/var/run/docker.sock" not in str(svc.get("volumes", [])), name
        assert not svc.get("privileged"), name
        if name in UNHARDENED:
            continue
        assert "no-new-privileges:true" in svc["security_opt"], name
        assert svc["cap_drop"] == ["ALL"] and svc["read_only"] is True, name
        for mount in svc.get("tmpfs", []):
            assert "noexec" in mount and "nosuid" in mount, (name, mount)


def test_every_service_has_a_healthcheck() -> None:
    dockerfile_checks = {
        "engine": "engine/Dockerfile"
    }  # splunk: the image's own HEALTHCHECK
    for name, svc in SERVICES.items():
        if name in dockerfile_checks:
            assert "HEALTHCHECK" in (ROOT / dockerfile_checks[name]).read_text()
        elif name == "migrate":
            assert svc["healthcheck"] == {
                "disable": True
            }  # one-shot, completion is the check
        elif name != "splunk":
            assert svc["healthcheck"]["test"], name


def test_published_ports_are_loopback_and_postgres_is_not_published() -> None:
    for name, svc in SERVICES.items():
        for port in svc.get("ports", []):
            # Only the https proxy may be opened wider, by the admin's HTTPS_BIND.
            assert port.startswith(("127.0.0.1:", "${HTTPS_BIND:-127.0.0.1}:")), (
                name,
                port,
            )
    assert "ports" not in SERVICES["postgres"]
    assert SERVICES["postgres-cli"]["profiles"] == ["cli"]
    assert SERVICES["https"]["profiles"] == ["https"]


def test_networks_separate_splunk_web_and_database() -> None:
    nets = COMPOSE["networks"]
    for internal in ("app", "data", "splunk_api"):
        assert nets[internal]["internal"] is True
    # Splunk never shares a network with the engine, the web UI or the database (DK-5).
    assert networks("splunk") == {"splunk"}
    assert not networks("splunk") & (
        networks("engine") | networks("web") | networks("postgres")
    )
    assert networks("splunk-api") == {"splunk", "splunk_api"}
    assert networks("postgres") == {"data"}
    assert "data" not in networks("web")
    for name in SERVICES:
        if "data" in networks(name):
            assert name in {"postgres", "migrate", "engine", "postgres-cli"}, name


def test_engine_trusts_only_the_web_container_for_forwarded_ips() -> None:
    """Trusting a wider range (or none) would let a client fake its IP, or make per-IP lockout
    lock every user at once behind the web container."""
    web_ip = SERVICES["web"]["networks"]["app"]["ipv4_address"]
    assert SERVICES["engine"]["environment"]["PARSEMAXXING_TRUSTED_PROXIES"] == web_ip
    (pool,) = COMPOSE["networks"]["app"]["ipam"]["config"]
    assert ipaddress.ip_address(web_ip) in ipaddress.ip_network(pool["subnet"])
    # Dynamic addresses come from ip_range, so no other container can take the web's address.
    assert ipaddress.ip_address(web_ip) not in ipaddress.ip_network(pool["ip_range"])
    assert {name for name in SERVICES if "app" in networks(name)} == {"web", "engine"}


def test_secrets_reach_only_the_services_that_need_them() -> None:
    def holders(secret: str) -> set[str]:
        return {n for n, s in SERVICES.items() if secret in s.get("secrets", [])}

    assert holders("pmx_kek") == {"engine"}  # never web, not migrate (DK-6, L2)
    assert holders("postgres_password") == {"postgres", "migrate"}
    assert holders("postgres_app_password") == {"engine", "migrate"}
    assert holders("pmx_proxy_hop") == {"web", "https"}
    assert all(s["file"].startswith("./secrets/") for s in COMPOSE["secrets"].values())
    assert "/secrets/" in (ROOT / ".gitignore").read_text().splitlines()
    for key in SERVICES["web"]["environment"]:
        assert "PASSWORD" not in key and "TOKEN" not in key and "KEY" not in key, key


def test_proxy_hop_header_comes_from_the_secret_and_replaces_the_clients() -> None:
    """Web passes X-Forwarded-For on only when X-Pmx-Hop matches (M1): Caddy must set it from
    the secret, replacing whatever the client sent, and nothing else may hold the value."""
    caddyfile = (ROOT / "scripts" / "Caddyfile").read_text()
    assert re.search(
        r"reverse_proxy web:3000 \{\s*header_up X-Pmx-Hop \{file\./run/secrets/pmx_proxy_hop\}\s*\}",
        caddyfile,
    )
    assert "header_up +X-Pmx-Hop" not in caddyfile  # "+" would append to a forged value
    env = SERVICES["web"]["environment"]
    assert env["PMX_PROXY_HOP_FILE"] == "/run/secrets/pmx_proxy_hop"


def test_engine_and_web_allow_the_same_origins() -> None:
    web, engine = (SERVICES[n]["environment"] for n in ("web", "engine"))
    assert engine["WEB_ORIGINS"] == web["WEB_ORIGINS"]
    assert "WEB_ORIGIN" not in engine  # one source of truth
    origins = web["WEB_ORIGINS"].split(",")
    assert "http://localhost:${WEB_PORT:-3000}" in origins
    assert "https://${PMX_PUBLIC_HOST:-localhost}:${HTTPS_PORT:-8443}" in origins


def test_every_image_is_pinned_by_digest() -> None:
    for name, svc in SERVICES.items():
        if "build" in svc:
            continue
        assert DIGEST.match(svc["image"]), name
    for dockerfile in (
        "engine/Dockerfile",
        "web/Dockerfile",
        "engine/tests/auth/openldap/Dockerfile",
    ):
        for line in (ROOT / dockerfile).read_text().splitlines():
            if line.startswith("FROM "):
                assert DIGEST.match(line.split()[1]), line
    pinned = re.compile(r"(?:image:|IMAGE=|SYFT=|TRIVY=)\s*(\S+)")
    for path in [ROOT / ".github/workflows/ci.yml", *(ROOT / "scripts").glob("*.*")]:
        for ref in pinned.findall(path.read_text()):
            if ref.startswith("parsemaxxing-"):  # the images this repo builds
                continue
            assert DIGEST.match(ref.strip("\"'")), (path.name, ref)


def test_python_lock_covers_every_runtime_dependency() -> None:
    import tomllib

    deps = tomllib.loads((ROOT / "engine/pyproject.toml").read_text())["project"][
        "dependencies"
    ]
    lock = (ROOT / "engine/requirements.lock").read_text()
    pinned = {
        m.lower().replace("_", "-")
        for m in re.findall(r"^([A-Za-z0-9_.-]+)==", lock, re.MULTILINE)
    }
    for dep in deps:
        name = re.match(r"[A-Za-z0-9_.-]+", dep)[0].lower().replace("_", "-")
        assert name in pinned, (
            f"{name} missing from engine/requirements.lock: run make lock"
        )
    assert "--require-hashes" in (ROOT / "engine/Dockerfile").read_text()
