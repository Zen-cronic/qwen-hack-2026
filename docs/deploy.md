# Deploy runbook — Alibaba Cloud SAS

The build runs on the SAS box (backend compute on Alibaba Cloud is the binding
proof-of-deployment reading). Two paths depending on whether the box can reach Docker Hub.

## Prerequisites

- An Alibaba Cloud SAS instance (already provisioned), Docker + compose installed.
- Port 80 open in the security group.
- A `.env` on the box with at least `QWEN_API_KEY` (copy from `.env.example`).

## Path A — build on the box (box has internet)

```bash
git clone <your public dailies repo> dailies && cd dailies
cp .env.example .env            # paste QWEN_API_KEY
# optional: seed the replay cache so demo clips are free
rsync -avz ./data/cache/ user@box:~/dailies/data/cache/
docker compose up -d --build    # builds web+app, starts nginx :80 -> app :8099
```

## Path B — build locally, ship the image (box is network-restricted)

```bash
docker compose build
# Project name is pinned to `dailies` in compose, so images are dailies-{app,web}
# regardless of the clone directory.
docker save dailies-app dailies-web | ssh user@box 'docker load'
scp docker-compose.yml .env user@box:~/dailies/
ssh user@box 'cd ~/dailies && docker compose up -d'
```

## Verify

`web` is gated on the app's `/api/health` readiness probe (compose `service_healthy`),
so once `docker compose up` returns healthy the public URL is never up-but-broken.

```bash
curl http://<box-ip>/api/health       # -> {"status":"ok","mode":"real"|"demo"}
curl http://<box-ip>/api/packs        # -> {"packs":[{"name":"short_drama",...}]}
open http://<box-ip>/                 # the SPA
docker compose ps                     # app should show (healthy)
```

## Modes

- **Real mode (default), `JUDGE_MODE=1`:** judges may trigger real generation up to the
  fresh-clip cap per session; cached replays are free. Watch the judge-reserve quota.
- **Demo mode, `DAILIES_DEMO=1`:** the whole pipeline runs on synthetic clips — real Tier-A
  CV + real assembly, **zero video quota**. Safest for a public URL that must survive the
  Jul 10–31 judging window. Set it in `.env` or the compose environment.

## Eligibility (manual, do on the box)

1. Bring the stack up and confirm the public URL loads.
2. **Capture the Alibaba Cloud Workbench screenshot** showing the running SAS resources —
   this is a mandatory judging gate ("No proof = not eligible"). Save it into the repo/blog.
3. Keep the URL live and unrestricted through the judging period.
