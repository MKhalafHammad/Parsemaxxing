# Test-only OpenLDAP server for engine/tests/auth/test_ldap_integration.py (marker
# ldap_integration). Debian's slapd on a base pinned by digest: it has the memberof overlay, and
# the test writes its own slapd.conf, certificates and seed data at run time. Never deployed.
FROM debian:bookworm-slim@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends slapd ldap-utils \
 && rm -rf /var/lib/apt/lists/*
EXPOSE 389 636
CMD ["sh", "-c", "mkdir -p /tmp/pmxdb && exec slapd -d 0 -f /cfg/slapd.conf -h \"ldap:/// ldaps:///\""]
