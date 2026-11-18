# Parsemaxxing web UI: the Next.js standalone server. Non-root; no secrets at build time; the
# engine URL is a server-side runtime variable (ENGINE_URL), never exposed to the browser.
# Pinned by tag, not digest: residual risk R12 in docs/threat-model.md.
FROM node:24-slim AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM node:24-slim
LABEL org.opencontainers.image.licenses="LicenseRef-PolyForm-Shield-1.0.0"
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./.next/static
# LICENSE and NOTICE come from the repo root (compose additional context "repo").
COPY --from=repo LICENSE NOTICE ./
USER node
EXPOSE 3000
CMD ["node", "server.js"]
