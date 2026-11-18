import tarfile

import pytest

from parsemaxxing.ta_builder import naming, package
from parsemaxxing.ta_builder.conf_writer import ConfValueError, write_conf
from parsemaxxing.ta_builder.naming import require_job, require_pmx_index, require_test_app, ta_name

APP = "TA-parsemaxxing-acme-vpn__test_abcd1234"


# --- conf writer (adversarial: structure injection) -----------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "x\n[script://./bin/evil.sh]",
        "x\r[script://./bin/evil.sh]",
        "x\\",  # line continuation
        "x\x00y",
        "x\x1by",
    ],
)
def test_writer_rejects_structure_changing_values(value):
    with pytest.raises(ConfValueError):
        write_conf({"acme:vpn": {"TIME_FORMAT": value}})


@pytest.mark.parametrize("stanza", ["a]\n[b", "x]y", "[x", "x\ny", "x y"])
def test_writer_rejects_bad_stanza_names(stanza):
    with pytest.raises(ConfValueError):
        write_conf({stanza: {"TZ": "UTC"}})


@pytest.mark.parametrize("key", ["", "1x", "a b", "a=b", "x\n"])
def test_writer_rejects_bad_keys(key):
    with pytest.raises(ConfValueError):
        write_conf({"acme:vpn": {key: "v"}})


def test_writer_renders_stanzas():
    text = write_conf({"acme:vpn__test_abcd1234_a1": {"LINE_BREAKER": "([\\r\\n]+)", "TZ": "UTC"}})
    assert text == "[acme:vpn__test_abcd1234_a1]\nLINE_BREAKER = ([\\r\\n]+)\nTZ = UTC\n"


# --- naming --------------------------------------------------------------------------------


@pytest.mark.parametrize("vendor", ["../x", "A-B", "x y", "", "x/y", "x;y"])
def test_ta_name_rejects_bad_parts(vendor):
    with pytest.raises(ValueError):
        ta_name(vendor, "vpn")


def test_names():
    assert ta_name("acme", "vpn") == "TA-parsemaxxing-acme-vpn"
    assert naming.test_app("acme", "vpn", "abcd1234") == APP
    assert naming.test_sourcetype("acme:vpn", "abcd1234", 2) == "acme:vpn__test_abcd1234_a2"
    with pytest.raises(ValueError):
        naming.test_sourcetype("acme:vpn", "abcd1234", 0)
    with pytest.raises(ValueError):
        require_job("ABC")
    with pytest.raises(ValueError, match="::"):
        naming.test_sourcetype("source::x", "abcd1234", 1)


@pytest.mark.parametrize("index", ["main", "pw", "pmx_", "pmx_*", "pmx_x OR index=main", "PW_x"])
def test_require_pmx_index_rejects(index):
    with pytest.raises(ValueError):
        require_pmx_index(index)


@pytest.mark.parametrize(
    "app", ["Splunk_TA_windows", "TA-parsemaxxing-acme-vpn", "TA-parsemaxxing-acme-vpn__test_../x"]
)
def test_require_test_app_rejects_real_or_foreign_apps(app):
    with pytest.raises(ValueError):
        require_test_app(app)


# --- package --------------------------------------------------------------------------------


def test_package_contents_and_hash(tmp_path):
    props = {"props": {"acme:vpn__test_abcd1234_a1": {"TZ": "UTC"}}}
    pkg = package.build(tmp_path, APP, "0.0.1", props)
    with tarfile.open(pkg.path) as tar:
        names = sorted(tar.getnames())
        meta = tar.extractfile(f"{APP}/metadata/default.meta").read().decode()
    assert names == [
        f"{APP}/default/app.conf",
        f"{APP}/default/props.conf",
        f"{APP}/metadata/default.meta",
    ]
    assert meta.startswith("[]\n")
    # Generated add-ons are the user's: no LICENSE file and no PolyForm text (NOTICE).
    with tarfile.open(pkg.path) as tar:
        assert not any(b"PolyForm" in tar.extractfile(m).read() for m in tar if m.isfile())
    assert pkg.sha256 == package.sha256(pkg.path)
    assert pkg.path.stat().st_mode & 0o777 == 0o644


def test_package_refuses_files_off_the_allowlist(tmp_path):
    with pytest.raises(ValueError, match="allowlist"):
        package.build(tmp_path, APP, "0.0.1", {"inputs": {"script://x": {"disabled": "0"}}})


def test_package_refuses_non_test_app(tmp_path):
    with pytest.raises(ValueError):
        package.build(tmp_path, "TA-parsemaxxing-acme-vpn", "0.0.1", {})


def test_packages_dir_must_be_private_real_dir(tmp_path):
    loose = tmp_path / "loose"
    loose.mkdir()
    loose.chmod(0o777)
    with pytest.raises(ValueError, match="writable"):
        package.packages_dir(loose)
    link = tmp_path / "link"
    link.symlink_to(tmp_path)
    with pytest.raises(ValueError, match="link"):
        package.packages_dir(link)


@pytest.mark.parametrize("value", ["x\x85y", "x\u2028y", "x\u2029y", "x\x9by"])
def test_writer_rejects_c1_and_unicode_line_separators(value):
    with pytest.raises(ConfValueError):
        write_conf({"acme:vpn": {"TIME_FORMAT": value}})
