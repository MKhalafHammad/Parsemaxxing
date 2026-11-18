"""Pure helpers of the Phase 11 lab probes. Nothing here talks to Splunk."""

import argparse
import io
import tarfile

import pytest

from parsemaxxing.tools.probes import lab
from parsemaxxing.tools.probes.probe_cim import summarize_model, summary_hash
from parsemaxxing.tools.probes.probe_delivery import looks_universal, require_push_target
from parsemaxxing.tools.probes.probe_read_role import checks
from parsemaxxing.tools.probes.probe_retention import retention_verdict


@pytest.mark.parametrize(
    ("version", "ok"),
    [
        ("10.2.0", True),
        ("10.6.1", True),
        ("10.10", True),
        ("10.1.9", False),
        ("9.4.3", False),
        ("", False),
        ("garbage", False),
    ],
)
def test_splunk_supported(version, ok):
    assert lab.splunk_supported(version) is ok


@pytest.mark.parametrize(
    ("splunk", "cim", "ok"),
    [
        ("10.2.0", "6.3.0", True),
        ("10.6.1", "6.2.9", False),
        ("10.6.1", "8.5.0", True),
        ("10.7.0", "6.3.0", False),
        ("10.7.0", "8.5.0", True),
        ("10.1.0", "8.5.0", False),
        ("10.2.0", "", False),
    ],
)
def test_cim_compatibility_table(splunk, cim, ok):
    assert lab.cim_ok(splunk, cim) is ok


@pytest.mark.parametrize(
    "name",
    [
        "main",
        "search",
        "TA-x__test_probe/../../etc",
        "../x__test_probe",
        "x__test_probe ",
        "TA-x__test_probex",
        "-x__test_probe",
        "x..y__test_probe",
        "x__test_probe\n",
    ],
)
def test_probe_app_name_rejects(name):
    with pytest.raises(ValueError):
        lab.require_probe_app(name)


def test_probe_app_name_accepts():
    assert lab.require_probe_app("Splunk_TA_acmeprobe__test_probe")


@pytest.mark.parametrize("st", ["main", "pmx_probe_x", "pmx_probe_x__test_probe | delete", ""])
def test_probe_sourcetype_rejects(st):
    with pytest.raises(ValueError):
        lab.require_probe_sourcetype(st)


@pytest.mark.parametrize("rel", ["/etc/passwd", "../x", "default/../../x", "a\\b"])
def test_build_tgz_rejects_escaping_paths(rel):
    with pytest.raises(ValueError):
        lab.build_tgz("TA-x__test_probe", {rel: "x"})


def test_build_tgz_keeps_every_file_under_the_app():
    data = lab.build_tgz("TA-x__test_probe", lab.probe_files("1.0.0", {"default/a.conf": "[a]"}))
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        members = tar.getmembers()
    assert {m.name for m in members} == {
        "TA-x__test_probe/default/app.conf",
        "TA-x__test_probe/default/a.conf",
        "TA-x__test_probe/metadata/default.meta",
    }
    assert all(m.isfile() for m in members)
    assert lab.build_tgz("TA-x__test_probe", {"a": "b"}) == lab.build_tgz(
        "TA-x__test_probe", {"a": "b"}
    )


def test_scrub_hides_ips_hosts_and_tokens():
    token = "eyJ" + "a" * 60
    out = lab.scrub(f"failed for 192.0.2.10 at splunk01.example.com with {token}")
    assert "192.0.2.10" not in out and "example.com" not in out and token not in out
    assert "<h-" in out and "[redacted]" in out


def test_anon_is_stable_and_hides_value():
    assert lab.anon("hf1.example.com") == lab.anon("hf1.example.com")
    assert "example" not in lab.anon("hf1.example.com")


def _args(**kw):
    base = {
        "host": "splunk.example.com",
        "port": 8089,
        "ca_file": None,
        "timeout": 5.0,
        "insecure_skip_tls_verify": False,
    }
    return argparse.Namespace(**(base | kw))


def test_connect_verifies_tls_by_default_and_reads_token_from_env(monkeypatch):
    seen = {}
    monkeypatch.setenv("PMX_LAB_READ_TOKEN", "t")
    monkeypatch.setattr(lab.client, "connect", lambda **kw: seen.update(kw))
    lab.connect(_args(), lab.READ_TOKEN_ENV)
    assert seen["verify"] is True and seen["splunkToken"] == "t"


def test_connect_insecure_only_with_flag(monkeypatch, capsys):
    seen = {}
    monkeypatch.setenv("PMX_LAB_READ_TOKEN", "t")
    monkeypatch.setattr(lab.client, "connect", lambda **kw: seen.update(kw))
    lab.connect(_args(insecure_skip_tls_verify=True), lab.READ_TOKEN_ENV)
    assert seen["verify"] is False
    assert "verification is OFF" in capsys.readouterr().out


def test_connect_refuses_missing_token_or_host(monkeypatch):
    monkeypatch.delenv("PMX_LAB_READ_TOKEN", raising=False)
    with pytest.raises(SystemExit):
        lab.connect(_args(), lab.READ_TOKEN_ENV)
    monkeypatch.setenv("PMX_LAB_READ_TOKEN", "t")
    with pytest.raises(SystemExit):
        lab.connect(_args(host=""), lab.READ_TOKEN_ENV)


def test_write_probes_need_the_flag():
    with pytest.raises(SystemExit):
        lab.require_lab_write(argparse.Namespace(lab_write=False))
    lab.require_lab_write(argparse.Namespace(lab_write=True))


# A data model definition written for this test (not Splunk's file), in the package layout.
MODEL = {
    "modelName": "Acme_Model",
    "objects": [
        {
            "objectName": "Acme_Root",
            "parentName": "BaseEvent",
            "constraints": [{"search": "tag=acme"}],
            "fields": [
                {
                    "fieldName": "action",
                    "type": "string",
                    "comment": {"recommended": True, "expected_values": ["allowed", "blocked"]},
                },
                {"fieldName": "note", "type": "string", "comment": "free text"},
            ],
            "calculations": [{"outputFields": [{"fieldName": "is_x", "type": "boolean"}]}],
        },
        {
            "objectName": "Acme_Child",
            "parentName": "Acme_Root",
            "constraints": [{"search": "action=blocked"}],
            "fields": [],
        },
    ],
}


def test_summarize_model_reads_fields_constraints_children():
    s = summarize_model(MODEL)
    root = s["datasets"]["Acme_Root"]
    assert root["constraints"] == ["tag=acme"]
    assert root["fields"]["action"] == {
        "type": "string",
        "recommended": True,
        "expected": ["allowed", "blocked"],
    }
    assert root["fields"]["note"]["expected"] == []
    assert "is_x" in root["fields"]
    assert s["datasets"]["Acme_Child"]["parent"] == "Acme_Root"


def test_summary_hash_detects_a_local_change():
    changed = {
        **MODEL,
        "objects": [{**MODEL["objects"][0], "constraints": [{"search": "x"}]}, MODEL["objects"][1]],
    }
    assert summary_hash(summarize_model(MODEL)) != summary_hash(summarize_model(changed))
    assert summary_hash(summarize_model(MODEL)) == summary_hash(summarize_model(dict(MODEL)))


def test_retention_verdict():
    assert retention_verdict("2592000").startswith("ok")
    assert retention_verdict(2592001).startswith("FAIL")
    assert retention_verdict(None).startswith("unreadable")


def test_looks_universal_fails_safe():
    assert looks_universal({}) is None
    assert looks_universal({"package": "universal_forwarder"}) is True
    assert looks_universal({"build": "splunkforwarder-10.6"}) is True
    assert looks_universal({"package": "enterprise"}) is False


@pytest.mark.parametrize("bad", ['x" OR index=*', "a b", "x|delete", ""])
def test_read_role_checks_reject_injected_names(bad):
    with pytest.raises(ValueError):
        checks(bad, "other", "st")
    with pytest.raises(ValueError):
        checks("idx", "other", bad)


@pytest.mark.parametrize(
    ("member", "given", "actual"),
    [
        ("https://shc1.example.com:8089", "guid-a", "guid-b"),  # another deployer
        ("https://shc1.example.com:8089", "", ""),  # unknown GUID
        ("https://shc1.example.com:8089/x?y", "guid-a", "guid-a"),  # extra path
        ("http://shc1.example.com:8089", "guid-a", "guid-a"),  # no TLS
    ],
)
def test_shc_push_refuses_unnamed_deployer_or_odd_member(member, given, actual):
    with pytest.raises(SystemExit):
        require_push_target(member, given, actual)


def test_shc_push_accepts_named_deployer():
    require_push_target("https://shc1.example.com:8089", "guid-a", "guid-a")
