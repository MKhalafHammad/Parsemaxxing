"""Adversarial: add-ons built before the rename keep their names (TA-parsewright-*, the
parsewright_<job>_ stanza prefix, the "Built and tested by Parsewright." marker), but only for a
TA already in the registry. A new build can never use them, and one add-on never mixes them.
"""

import contextlib
import gzip
import hashlib

import pytest
from conftest import settings

from parsemaxxing.guardrails import conf_gate
from parsemaxxing.guardrails.index_time import GuardrailBlock
from parsemaxxing.orchestrator import promote
from parsemaxxing.orchestrator.update import split_stages
from parsemaxxing.ta_builder import package
from parsemaxxing.ta_builder.naming import (
    require_real_app,
    require_test_app,
    stanza_prefix,
    ta_name,
)
from parsemaxxing.tools.splunk_client import SplunkClient, SplunkError

OWNER, JOB = "own00001", "upd00001"
LEGACY, NEW = "TA-parsewright-acme-fw", "TA-parsemaxxing-acme-fw"
ST = "acme:fw"
LEGACY_CONFS = {  # a v1 add-on as the pre-rename code built it
    "props": {ST: {"TZ": "UTC", "REPORT-x": f"parsewright_{OWNER}_delims"}},
    "transforms": {f"parsewright_{OWNER}_delims": {"DELIMS": '"|"', "FIELDS": '"a"'}},
    "eventtypes": {f"parsewright_{OWNER}_t": {"search": f"sourcetype={ST}"}},
}
# sha256 of the uncompressed tar the pre-rename builder (main) wrote for LEGACY_CONFS at 1.0.0.
LEGACY_TAR_SHA256 = "ed72f3519f1ef42e838e15b46d14764066caf4b297be826203cc3e9ab6a0470c"


@pytest.fixture
def pkgs(tmp_path):
    d = tmp_path / "packages"
    d.mkdir(mode=0o755)
    return d


def tar_sha(pkg: package.Package) -> str:
    return hashlib.sha256(gzip.decompress(pkg.path.read_bytes())).hexdigest()


# --- a new build may never use the legacy forms ---------------------------------------------


def test_a_new_build_named_ta_parsewright_is_refused(tmp_path, pkgs):
    assert ta_name("acme", "fw") == NEW  # the only name a new build is given
    with pytest.raises(ValueError):
        ta_name("acme", "fw", "acme")  # brand= is never free text
    with pytest.raises(ValueError, match="not a Parsemaxxing TA name"):
        require_real_app(LEGACY)
    with pytest.raises(ValueError):
        package.build_promoted(pkgs, LEGACY, "1.0.0", LEGACY_CONFS)  # not registered
    with pytest.raises(ValueError):  # never as a test identity, even for a registered TA
        require_test_app(f"{LEGACY}__test_{JOB}")
    with pytest.raises(ValueError):
        require_real_app(f"{LEGACY}__test_{JOB}", registered=True)
    # a new-build record that claims a legacy name is refused before anything reaches Splunk
    record = {
        "job": JOB,
        "app": LEGACY,
        "test_app": f"{NEW}__test_{JOB}",
        "sourcetype": ST,
        "vendor": "acme",
        "product": "fw",
    }
    with pytest.raises(ValueError):
        promote._validated(record)
    client = SplunkClient(settings(pkgs), search=object(), deploy=object())
    fake = package.Package(pkgs / "x.tgz", LEGACY, "0" * 64)
    with pytest.raises(ValueError):  # promotion install (new builds only) refuses it
        client.install(fake, promotion=True)


def test_a_new_build_emitting_parsewright_stanzas_is_refused():
    legacy = {
        "props": {ST: {"REPORT-x": f"parsewright_{JOB}_delims"}},
        "transforms": {f"parsewright_{JOB}_delims": {"DELIMS": '"|"'}},
    }
    with pytest.raises(GuardrailBlock, match=r"outside this job|must start with"):
        conf_gate.check(legacy, JOB, ST)  # every test deploy and new build
    with pytest.raises(GuardrailBlock):
        conf_gate.check(legacy, JOB, ST, NEW)  # a new-named TA's promotion
    eventtype = {"props": {ST: {}}, "eventtypes": {f"parsewright_{JOB}_t": {"search": "x"}}}
    with pytest.raises(GuardrailBlock, match="must start with"):
        conf_gate.check(eventtype, JOB, ST)


# --- mixed: one add-on, one brand -----------------------------------------------------------


def test_mixed_prefixes_are_refused():
    # Defined behaviour: the stanza prefix follows the app's own name, so a legacy app with
    # parsemaxxing_ stanzas, or a new app with parsewright_ ones, fails the final gate.
    new_stanzas = {
        "props": {ST: {"REPORT-x": f"parsemaxxing_{OWNER}_delims"}},
        "transforms": {f"parsemaxxing_{OWNER}_delims": {"DELIMS": '"|"'}},
    }
    with pytest.raises(GuardrailBlock):
        conf_gate.check(new_stanzas, OWNER, ST, LEGACY)
    with pytest.raises(GuardrailBlock):
        conf_gate.check(LEGACY_CONFS, OWNER, ST, NEW)
    conf_gate.check(new_stanzas, OWNER, ST, NEW)
    conf_gate.check(LEGACY_CONFS, OWNER, ST, LEGACY)
    # an app name that only looks legacy gets the current prefix (brand comes from a full match)
    assert stanza_prefix(OWNER, "TA-parsewright-") == f"parsemaxxing_{OWNER}_"


# --- a registered legacy add-on can still be updated and rolled back -------------------------


def test_legacy_v1_rebuilds_byte_for_byte(pkgs):
    v1 = package.build_promoted(pkgs, LEGACY, "1.0.0", LEGACY_CONFS, registered=True)
    assert tar_sha(v1) == LEGACY_TAR_SHA256  # same bytes as the pre-rename builder
    files = promote.package_files(v1.path.read_bytes(), LEGACY)
    assert "description = Built and tested by Parsewright." in files["default/app.conf"]
    again = package.build_promoted(
        pkgs, LEGACY, "1.0.0", promote.confs_from_files(files), registered=True
    )
    assert again.sha256 == v1.sha256


def test_a_registered_legacy_update_tests_under_new_names_and_promotes_under_its_own(pkgs):
    stages = split_stages(LEGACY_CONFS, ST, OWNER, JOB, LEGACY)
    transforms = stages["extraction"]["transforms"]
    assert list(transforms) == [f"parsemaxxing_{JOB}_delims"]  # test identity: current names
    st = f"{ST}__test_{JOB}_a1"
    test_confs = {
        "props": {st: {**stages["index"], **stages["extraction"]["props"]}},
        "transforms": transforms,
        "eventtypes": {n: {"search": f"sourcetype={st}"} for n in stages["cim"]["eventtypes"]},
    }
    conf_gate.check(test_confs, JOB, st)
    test_pkg = package.build(pkgs, f"{NEW}__test_{JOB}", "0.0.1", test_confs)
    record = {
        "job": JOB,
        "owner_job": OWNER,
        "app": LEGACY,
        "test_app": test_pkg.app,
        "sourcetype": ST,
        "test_sourcetype": st,
    }
    back = promote.confs_from_files(promote.renamed_files(test_pkg.path.read_bytes(), record))
    assert back == LEGACY_CONFS  # the add-on keeps its own stanza names
    conf_gate.check(back, OWNER, ST, LEGACY)


def test_an_update_record_may_keep_its_registered_legacy_name(tmp_path, pkgs):
    test_pkg = package.build(pkgs, f"{NEW}__test_{JOB}", "0.0.1", {"props": {ST: {}}})
    sample = tmp_path / "s.log"
    sample.write_text("a\n")
    kw = dict(vendor="acme", product="fw", sourcetype=ST, test_sourcetype=ST, sample=sample)
    update = {"update_of": LEGACY, "owner_job": OWNER, "version_from": "1.0.0"}
    record = promote.record_passed_run(tmp_path / "runs", JOB, test_pkg, update=update, **kw)
    assert record["app"] == LEGACY
    fresh = promote.record_passed_run(tmp_path / "runs2", JOB, test_pkg, **kw)
    assert fresh["app"] == NEW  # a new build of the same vendor/product gets the new name


class LegacyStore:
    def __init__(self, versions, registered=True):
        self.versions, self.current, self.registered = versions, "1.1.0", registered

    def ta(self, app):
        if not self.registered:
            return None
        return {"app": LEGACY, "sourcetype": ST, "owner_job": OWNER, "current_version": "1.1.0"}

    def ta_versions(self, app):
        return self.versions

    @contextlib.contextmanager
    def ta_lock(self, app):
        yield

    def set_current_version(self, app, previous, version, event):
        self.current = version


class Updates:
    def __init__(self):
        self.updated = []

    def update_app(self, pkg, expected_version):
        self.updated.append(pkg)


def _kept(tmp_path, data: bytes) -> None:
    runs = tmp_path / "runs"
    (runs / OWNER).mkdir(parents=True, mode=0o700)
    runs.chmod(0o700)
    (runs / OWNER / "promoted.tgz").write_bytes(data)


def test_a_registered_legacy_app_rolls_back_exactly(tmp_path, pkgs):
    v1 = package.build_promoted(pkgs, LEGACY, "1.0.0", LEGACY_CONFS, registered=True)
    _kept(tmp_path, v1.path.read_bytes())
    v1.path.unlink()
    store = LegacyStore([{"version": "1.0.0", "job_id": OWNER, "sha256": v1.sha256}])
    splunk = Updates()
    promote.rollback(store, tmp_path / "runs", LEGACY, "1.0.0", splunk, pkgs, out=lambda *a: None)
    assert store.current == "1.0.0" and [p.sha256 for p in splunk.updated] == [v1.sha256]


def test_a_legacy_name_not_in_the_registry_is_refused(tmp_path, pkgs):
    v1 = package.build_promoted(pkgs, LEGACY, "1.0.0", LEGACY_CONFS, registered=True)
    _kept(tmp_path, v1.path.read_bytes())
    store = LegacyStore([{"version": "1.0.0", "job_id": OWNER, "sha256": v1.sha256}], False)
    splunk = Updates()
    with pytest.raises(promote.TransitionRefused, match="not in the TA registry"):
        promote.rollback(store, tmp_path / "runs", LEGACY, "1.0.0", splunk, pkgs)
    assert splunk.updated == []


def test_update_promotion_of_an_unregistered_legacy_name_is_refused(pg, tmp_path):
    records = promote.PgRecords(pg.conn, tmp_path)
    record = {"app": LEGACY, "sourcetype": ST, "owner_job": OWNER, "version_from": "1.0.0"}
    with pytest.raises(promote.TransitionRefused, match="not in the TA registry"):
        promote._registry_allows_update(records, record)


class AppInfo:
    def __init__(self):
        self.posts = []

    def post(self, path, **kw):
        self.posts.append(path)


@pytest.mark.parametrize(
    "app,marker,ok",
    [
        (LEGACY, "Built and tested by Parsewright.", True),
        (LEGACY, package.DESCRIPTION, False),  # mixed: legacy name, new marker
        (NEW, "Built and tested by Parsewright.", False),  # mixed: new name, legacy marker
        (NEW, package.DESCRIPTION, True),
    ],
)
def test_in_place_update_checks_the_apps_own_marker(tmp_path, pkgs, monkeypatch, app, marker, ok):
    client = SplunkClient(settings(pkgs), search=AppInfo(), deploy=AppInfo())
    monkeypatch.setattr(client, "app_info", lambda _: {"version": "1.0.0", "description": marker})
    pkg = package.build_promoted(pkgs, app, "1.1.0", {"props": {ST: {}}}, registered=True)
    if ok:
        client.update_app(pkg, expected_version="1.0.0")
        assert client.deploy.posts == ["apps/local"]
    else:
        with pytest.raises(SplunkError, match="not installed by Parsemaxxing"):
            client.update_app(pkg, expected_version="1.0.0")
        assert client.deploy.posts == []
