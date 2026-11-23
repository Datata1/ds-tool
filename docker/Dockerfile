# AP-Planer im Browser (z.B. auf einem Server für den ganzen Stamm).
# Gleiche Oberfläche wie die Desktop-App; Daten liegen im Volume /data.
#
#   docker compose -f docker/compose.yaml up -d   → http://localhost:8000

FROM node:22-slim AS web
WORKDIR /web
COPY desktop/package.json desktop/package-lock.json ./
RUN npm ci --no-fund --no-audit
COPY desktop/ ./
RUN npm run build

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy AP_HOME=/data TZ=Europe/Berlin
WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
COPY docs ./docs
COPY .claude/skills ./.claude/skills
RUN uv sync --locked --no-dev
COPY --from=web /web/dist ./web
VOLUME ["/data"]
EXPOSE 8000
# No token: the browser page talks to the same origin. Only reachable via the port mapping in
# compose.yaml (127.0.0.1) - put a reverse proxy with login in front before exposing it.
CMD ["uv", "run", "--no-dev", "ap-planner-server", "--host", "0.0.0.0", "--port", "8000", "--no-token", "--static", "/app/web"]
