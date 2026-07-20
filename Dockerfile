# One multi-stage Dockerfile, three targets (compose builds `app` and `web`).

# Stage 1 — build the SPA to static assets.
FROM node:22-alpine AS spa
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build            # -> /web/dist

# Stage 2 — the FastAPI backend (uvicorn). ffmpeg for assembly; libglib for opencv.
FROM python:3.12-slim AS app
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml LICENSE ./
COPY server/ ./server/
COPY packs/ ./packs/
# Catalog layer: migrations run in-process at first pool open (server/db.py),
# and seeding runs in-container (docker compose exec app python scripts/seed_catalog.py).
COPY alembic.ini ./
COPY alembic/ ./alembic/
COPY scripts/ ./scripts/
RUN pip install --no-cache-dir .
# Paths are stored relative to the working dir (data/...); keep DATA_DIR relative
# and mount the volume at /app/data so container behavior matches local dev exactly.
ENV DATA_DIR=data
EXPOSE 8099
CMD ["uvicorn", "server.app:create_production_app", "--factory", "--host", "0.0.0.0", "--port", "8099"]

# Stage 3 — nginx serving the SPA and proxying /api to the app service.
FROM nginx:alpine AS web
COPY --from=spa /web/dist /usr/share/nginx/html
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
