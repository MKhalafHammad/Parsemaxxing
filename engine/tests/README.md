# engine/tests

pytest suite for the `parsemaxxing` package, mirroring its layout. Includes the adversarial regression suite in `adversarial/` (nullQueue, newline injection, path traversal, injected log lines, constant-value gaming, forbidden searches). PostgreSQL tests are skipped when the test database is unreachable. Synthetic data only.

## LDAP against a real OpenLDAP (`ldap_integration`)

`auth/test_ldap_integration.py` builds `auth/openldap/Dockerfile` (Debian slapd with the memberof overlay, base image pinned by digest; image tag `pmx-test-openldap:bookworm-1`, built once and reused), generates a throwaway CA and a `localhost` server certificate with `cryptography`, starts the container with LDAPS and StartTLS published on random 127.0.0.1 ports, seeds synthetic `acme.example` users and groups, and removes it afterwards. It needs the `docker` CLI and a daemon that can build (the build uses `--network host` and fetches Debian packages) and publish ports to 127.0.0.1. Without docker the tests skip; with `PARSEMAXXING_LDAP_IT=1` (CI) they fail instead. Run them alone with `pytest -m ldap_integration engine/tests/auth`. The logic tests in `auth/test_ldap.py` use ldap3's `MOCK_SYNC` and need no docker.
