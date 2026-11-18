# Parsemaxxing web UI: the Next.js standalone server. Non-root; no secrets at build time; the
# engine URL is a server-side runtime variable (ENGINE_URL), never exposed to the browser.
# Base image pinned by digest (R12); scripts/refresh_digests.py updates it for review.
FROM node:24-slim@sha256:dc26ae92c9fb15cf6b1d63e20f0944b2efe0f115b20e00be48fb23fceb061c54 AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM node:24-slim@sha256:dc26ae92c9fb15cf6b1d63e20f0944b2efe0f115b20e00be48fb23fceb061c54
LABEL org.opencontainers.image.licenses="LicenseRef-PolyForm-Shield-1.0.0"
# The server needs only node: drop npm, npx and corepack (and their bundled dependencies).
RUN rm -rf /usr/local/lib/node_modules /usr/local/bin/npm /usr/local/bin/npx /usr/local/bin/corepack
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./.next/static
# LICENSE and NOTICE come from the repo root (compose additional context "repo").
COPY --from=repo LICENSE NOTICE ./
USER node
EXPOSE 3000
CMD ["node", "server.js"]
