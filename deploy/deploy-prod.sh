#!/usr/bin/env bash
# Production deploy for Dailies on the Alibaba Cloud SAS box.
#
# Builds and (re)starts whatever is CURRENTLY checked out in ~/dailies; syncing
# the checkout to the target commit is the caller's job. The CI workflow
# (.github/workflows/deploy-prod.yml) does `git fetch && reset --hard origin/main`
# before invoking this — the one safe place to update the tree, since a script
# can't reliably git-reset the file it is itself executing. For a manual deploy
# run `git pull` first; for a rollback `git reset --hard <good-sha>` first — this
# script builds the current checkout and won't fight either.
#
# Secrets are read from ~/dailies/.env (managed once on the box, gitignored) —
# this script never writes them. The SPA is built inside the Docker `spa` stage,
# so there is no host-side node build step.

set -euo pipefail

REPO_DIR="${DAILIES_DIR:-$HOME/dailies}"
ENV_NAME="${ENV_NAME:-prod}"

cd "$REPO_DIR"
echo "==> Deploying Dailies (env=$ENV_NAME) @ $(git rev-parse --short HEAD 2>/dev/null || echo unknown) in $REPO_DIR"

# Fail loudly if the box was never seeded with secrets.
if [[ ! -f .env ]]; then
    echo "Error: .env not found in $REPO_DIR." >&2
    echo "       Seed it once on the box: cp .env.example .env && edit QWEN_API_KEY." >&2
    exit 1
fi

echo "==> Building images and (re)starting the stack"
docker compose up -d --build --remove-orphans

echo "==> Reclaiming disk (dangling images/layers)"
docker image prune -f

# Readiness gate. compose already holds `web` until `app` is service_healthy,
# but we confirm the app container reports healthy before calling the deploy green.
# Probe the container's own healthcheck (host may not have curl).
echo "==> Waiting for the app container to report healthy"
app_cid="$(docker compose ps -q app)"
if [[ -z "$app_cid" ]]; then
    echo "Error: app container not found after compose up." >&2
    docker compose ps
    exit 1
fi

status="starting"
for _ in $(seq 1 60); do
    status="$(docker inspect --format '{{.State.Health.Status}}' "$app_cid" 2>/dev/null || echo starting)"
    if [[ "$status" == "healthy" ]]; then
        echo "==> app is healthy — deploy green"
        docker compose ps
        exit 0
    fi
    sleep 2
done

echo "Error: app did not become healthy within ~120s (last status: $status)." >&2
docker compose ps
docker compose logs --tail=80 app
exit 1
