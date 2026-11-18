# Parsemaxxing engine: the API and its worker pool (`parsemaxxing serve`).
# Non-root, slim, no Docker socket (threat T7.5): the engine reaches Splunk over REST only.
# Pinned by tag, not digest: residual risk R12 in docs/threat-model.md.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY pyproject.toml README.md ./
COPY parsemaxxing ./parsemaxxing
RUN pip install --no-cache-dir . \
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
