# Parsemaxxing engine: the API and its worker pool (`parsemaxxing serve`).
# Non-root, slim, no Docker socket (threat T7.5): the engine reaches Splunk over REST only.
# Base image pinned by digest (R12); scripts/refresh_digests.py updates it for review.
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
LABEL org.opencontainers.image.licenses="LicenseRef-PolyForm-Shield-1.0.0"

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

# age and the PostgreSQL 17 client for encrypted backups (scripts/backup.sh, `parsemaxxing
# backup`). Debian packages follow the pinned base image's release (trixie); the upgrade takes
# security fixes published after the base image was built (Trivy gate).
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends age postgresql-client-17 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
# Every dependency, the build backend included, pinned with hashes (make lock).
COPY requirements.lock ./
RUN pip install --require-hashes --no-deps -r requirements.lock
COPY pyproject.toml README.md ./
# LICENSE and NOTICE come from the repo root (compose additional context "repo").
COPY --from=repo LICENSE NOTICE ./
COPY parsemaxxing ./parsemaxxing
# --no-deps: nothing outside the lock; --no-build-isolation: the locked hatchling builds it.
RUN pip install --no-deps --no-build-isolation . \
    && useradd --system --uid 10001 --home-dir /app parsemaxxing \
    # The packages folder must be owned by the engine user and not group/world-writable
    # (T5.9); Splunk reads it read-only through the shared volume.
    && install -d -o parsemaxxing -g parsemaxxing -m 0755 /opt/parsemaxxing/packages \
    && install -d -o parsemaxxing -g parsemaxxing -m 0700 /app/.runs

USER parsemaxxing
ENV PARSEMAXXING_PACKAGES_DIR=/opt/parsemaxxing/packages PARSEMAXXING_RUNS_DIR=/app/.runs
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=4)"
# The engine container is reached as "engine" on the compose network.
CMD ["parsemaxxing", "--env-file", "/dev/null", "serve", "--host", "0.0.0.0", "--port", "8080", "--workers", "4"]
