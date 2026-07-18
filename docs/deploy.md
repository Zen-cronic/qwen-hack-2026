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

## Continuous deployment (push to `main` → SAS)

A merge to `main` is a release. GitHub Actions (`.github/workflows/deploy-prod.yml`)
SSHes into the SAS box, syncs the checkout to `origin/main`, then runs
`deploy/deploy-prod.sh`, which rebuilds the stack and gates on the app healthcheck.

```
push/merge → main
  → GitHub Actions (appleboy/ssh-action)
    → ssh SAS box: git fetch && reset --hard origin/main
      → deploy/deploy-prod.sh: docker compose up -d --build → wait for healthy
```

No Doppler and no host-side node build: secrets live in `~/dailies/.env` on the box, and the
SPA is built inside the Docker `spa` stage. CI's only job is SSH reach — the single long-lived
secret in GitHub is the deploy SSH key; `QWEN_API_KEY` never leaves the box.

### One-time setup

1. **SAS instance + Docker.** Provision an Alibaba Cloud [Simple Application
   Server](https://www.alibabacloud.com/help/en/simple-application-server/product-overview/what-is-simple-application-server)
   (an app image with Docker preinstalled, or install Docker + the compose plugin yourself).
   Open **port 80** (and **22** for SSH) in the SAS firewall / security group. If you deploy as
   a non-root user, add it to the `docker` group (`sudo usermod -aG docker $USER`, re-login).

2. **Dedicated CI SSH key.** Generate a keypair used only by the pipeline and authorize it on the box:
   ```bash
   ssh-keygen -t ed25519 -C "dailies-ci" -f ./dailies_ci -N ""
   ssh-copy-id -i ./dailies_ci.pub <user>@<sas-public-ip>   # appends to ~/.ssh/authorized_keys
   ```
   Keep the **private** key (`dailies_ci`) for the GitHub secret; the public key stays on the box.

3. **GitHub → Settings → Secrets and variables → Actions.**
   - Secrets: `SERVER_HOST` = SAS **public IP**, `SERVER_USER` = the SSH user (`root` or your deploy
     user), `SERVER_SSH_KEY` = the **private** key from step 2 (full PEM, including the header/footer lines).
   - Variables: `ENV_NAME` = `prod`. (This is the hook for future `dev`/`staging` — copy the workflow,
     point it at another box, change `ENV_NAME`.)
   - Optional gate: **Settings → Environments → production → Required reviewers** turns each deploy into
     a one-click manual approval.

4. **Clone the repo onto the box** at `~/dailies`. While the repo is **private** (it stays private
   until the submission flip), clone with a fine-grained GitHub **PAT** (Repository access: this
   repo; permissions **Contents: read**, **Metadata: read**) — once it flips public, an anonymous
   clone works and future `git fetch` needs no token:
   ```bash
   git clone https://github.com/Zen-cronic/qwen-hack-2026.git ~/dailies
   ```
   PAT-based clone while private:
   ```bash
   export GITHUB_TOKEN=<pat>
   git clone https://oauth2:${GITHUB_TOKEN}@github.com/Zen-cronic/qwen-hack-2026.git ~/dailies
   ```
   (Note: embedding the token in the remote URL persists it in `~/dailies/.git/config`. Prefer a git
   credential helper if that matters.)

5. **Seed secrets on the box** (once — CD never rewrites this file):
   ```bash
   cd ~/dailies && cp .env.example .env
   # edit .env: paste QWEN_API_KEY; set DAILIES_DEMO=1 for a zero-quota public URL, JUDGE_MODE as desired
   ```

6. **First deploy.** Either push to `main`, hit **Run workflow** (`workflow_dispatch`) in the Actions tab,
   or run it by hand on the box: `chmod +x deploy/deploy-prod.sh && ./deploy/deploy-prod.sh`.

### Per-deploy behavior & rollback

Each run hard-resets the box checkout to `origin/main` (safe: `.env` and `data/` are gitignored, so
secrets and the persisted cache/run-state volume are untouched), rebuilds, prunes dangling images, and
waits up to ~120 s for the app container to report `healthy` — exiting non-zero (with `docker compose
logs`) if it doesn't, so a broken build fails the Action instead of silently serving.

The `git fetch`/`reset` lives in the **workflow**, not `deploy/deploy-prod.sh`: a script can't reliably
`git reset` the file it is itself running, and doing the sync once keeps it out of the script.
`deploy/deploy-prod.sh` therefore builds **whatever is checked out** — which is exactly why the rollback
below works (the script won't re-sync you back to the bad tip).

To **roll back**, either revert the offending commit on `main` and push, or on the box:
```bash
cd ~/dailies && git reset --hard <good-sha> && ./deploy/deploy-prod.sh
```

### Failure signatures

- **Run fails in <10 s, log ends `Error: missing server host`** — step 3 was never done: the
  `SERVER_HOST`/`SERVER_USER`/`SERVER_SSH_KEY` secrets are absent (`gh secret list` returns
  nothing), so the SSH action aborts before opening a connection. This is exactly what a run
  failing in seconds means — auth failures take ~30 s of retries, script failures take minutes;
  a near-instant death is always missing configuration, and no amount of workflow-file editing
  fixes it.
- **Run fails after minutes at the health gate** — the build broke or the app container never
  reported `healthy`; the Action prints `docker compose logs` for exactly this case.

## Eligibility (manual, do on the box)

1. Bring the stack up and confirm the public URL loads.
2. **Capture the Alibaba Cloud Workbench screenshot** showing the running SAS resources —
   this is a mandatory judging gate ("No proof = not eligible"). Save it into the repo/blog.
3. Keep the URL live and unrestricted through the judging period.
