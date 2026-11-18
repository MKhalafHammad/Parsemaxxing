"""TA, test-identity and index naming rules (design: "Test identity", "TA builder")."""

import re

PART = re.compile(r"[a-z0-9_:-]+")
JOB = re.compile(r"[a-z0-9]{4,16}")
INDEX = re.compile(r"pmx_[a-z0-9_-]+")
TEST_APP = re.compile(r"TA-parsemaxxing-[a-z0-9_:-]+-[a-z0-9_:-]+__test_[a-z0-9]{4,16}")
TA = re.compile(r"TA-parsemaxxing-[a-z0-9_:-]+-[a-z0-9_:-]+")
BRAND = "parsemaxxing"
TA_PREFIX = f"TA-{BRAND}-"
# Add-ons built before the rename keep their names, stanza prefixes and app.conf marker (a Splunk
# app's name is its folder). Accepted only for an add-on already in the TA registry.
LEGACY_BRAND = "parsewright"
LEGACY_TA = re.compile(rf"TA-{LEGACY_BRAND}-[a-z0-9_:-]+-[a-z0-9_:-]+")


def _part(value: str, what: str) -> str:
    if not PART.fullmatch(value):
        raise ValueError(f"{what} {value!r} must match ^[a-z0-9_:-]+$")
    return value


def require_job(job: str) -> str:
    if not JOB.fullmatch(job):
        raise ValueError(f"job id {job!r} must match ^[a-z0-9]{{4,16}}$")
    return job


def ta_name(vendor: str, product: str, brand: str = BRAND) -> str:
    """New builds always get BRAND; brand= is only ever brand(<a registered app's name>)."""
    if brand not in (BRAND, LEGACY_BRAND):
        raise ValueError(f"unknown brand {brand!r}")
    return f"TA-{brand}-{_part(vendor, 'vendor')}-{_part(product, 'product')}"


def brand(app: str) -> str:
    """The naming generation of a (validated) real TA name: legacy add-ons keep theirs."""
    return LEGACY_BRAND if LEGACY_TA.fullmatch(app) else BRAND


def stanza_prefix(job: str, app: str | None = None) -> str:
    """<brand>_<job>_ for transform and eventtype names; one brand per add-on, so a legacy app
    with new-prefix stanzas (or a new app with legacy ones) fails the final gate."""
    return f"{brand(app) if app else BRAND}_{require_job(job)}_"


def test_app(vendor: str, product: str, job: str) -> str:
    return f"{ta_name(vendor, product)}__test_{require_job(job)}"


RESERVED_SOURCETYPES = {"default"}


def require_sourcetype(sourcetype: str) -> str:
    """A props stanza name that can only be a sourcetype stanza, and never [default] (H1)."""
    _part(sourcetype, "sourcetype")
    if "::" in sourcetype:  # would make a source::, host:: or rule:: stanza, not a sourcetype
        raise ValueError(f"sourcetype {sourcetype!r} must not contain '::'")
    if sourcetype in RESERVED_SOURCETYPES:
        raise ValueError(f"sourcetype {sourcetype!r} is reserved")
    return sourcetype


def test_sourcetype(sourcetype: str, job: str, attempt: int) -> str:
    """Each attempt gets a new sourcetype: the case proven to apply without reload (Q3)."""
    if attempt < 1:
        raise ValueError("attempt starts at 1")
    return f"{require_sourcetype(sourcetype)}__test_{require_job(job)}_a{attempt}"


def require_test_app(app: str) -> str:
    """Guard for every install or uninstall call made with the near-admin deploy token (T7.4)."""
    if not TEST_APP.fullmatch(app):
        raise ValueError(f"refusing app {app!r}: not a Parsemaxxing test app")
    return app


def require_real_app(app: str, registered: bool = False) -> str:
    """Guard for promotion: a Parsemaxxing TA name with no test suffix. registered=True (only
    after the caller found the app in the TA registry) also accepts a legacy name."""
    ok = TA.fullmatch(app) or (registered and LEGACY_TA.fullmatch(app))
    if not ok or "__test_" in app:
        raise ValueError(f"refusing app {app!r}: not a Parsemaxxing TA name")
    return app


def require_pmx_index(index: str) -> str:
    """Full match, not a prefix check: the name is also interpolated into SPL (T5.1)."""
    if not INDEX.fullmatch(index):
        raise ValueError(f"refusing index {index!r}: test indexes must match pmx_[a-z0-9_-]+")
    return index
