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
  fresh-clip cap per session — 2 drafts and 2 fresh **t2v** finals (`server/budget.py`);
  cached replays are free and uncapped. Past the cap the run still completes: the passing
  draft is certified in place of the final. Watch the judge-reserve quota.
  Pay-as-you-go must stay enabled in the Model Studio console ("Stop When Free Quota Is
  Used Up" **off**), or voucher credit can't be spent and billable calls hard-fail once
  the per-model free grant runs out.

  > **Promotion sits outside the governor — know this before leaving the URL unattended.**
  > `governed_gen_video` wraps `gen_video_fn` only, and promotion now renders through
  > `patch_video_fn` (frame-anchored `wan2.2-i2v-flash`, `server/app.py`), which is
  > deliberately unwrapped so anchored work draws on the separate i2v pool rather than
  > competing with drafts. The consequence is that `fresh_final_cap` does not bound a live
  > run. What bounds it is the per-project `final_cap` (4) plus the motion-contract skip:
  > a 3-shot run spends **2** fresh i2v clips on promotion, plus one per anchored repair,
  > against a **50 s = 10-clip** i2v pool. That is a handful of uncached judge runs, not an
  > unbounded drain — but it is not the 2-clip ceiling the governor implies either. For a
  > URL left unattended, prefer `DAILIES_DEMO=1`.
- **Demo mode, `DAILIES_DEMO=1`:** the whole pipeline runs on synthetic clips — real Tier-A
  CV + real assembly, **zero video quota**. Safest for a public URL that must survive the
  Jul 10–31 judging window. Set it in `.env` or the compose environment.

## Catalog layer (optional, off by default)

`CATALOG_ENABLED=1` turns on the production data layer: a `postgres:18-alpine` compose
sidecar (`db`) holding published runs relationally (projects, shots, takes, assertion
results, cast/voices, ledger), with media uploaded to a private Alibaba OSS bucket and
**object keys — never signed URLs — in the columns**. Live runs are untouched: the
in-memory Store + atomic `state.json` stays the source of truth, and a run publishes into
the catalog only when it finishes (`Pipeline._publish_catalog`) or via
`POST /api/projects/{id}/publish`. With the flag off (default), no DB connection is ever
opened and no OSS code is imported — today's app, byte for byte.

One-time cloud setup (console):

1. **OSS bucket** in the box's region (`us-west-1`, Silicon Valley — same region makes
   server-side traffic free over the internal endpoint), ACL **private**.
2. **RAM user** `dailies-app`, programmatic access only, least-privilege policy:
   `oss:PutObject/GetObject/HeadObject` on `<bucket>/*`, `oss:ListObjects` on the bucket.
3. **Bucket CORS** (for any SPA fetch/XHR; plain `<video>/<img>` tags don't need it):
   AllowedOrigins = the box URL + `http://localhost:5173`, methods GET/HEAD, expose
   `ETag, Content-Length, Content-Range, Accept-Ranges`.
4. Sanity from the box: `curl -sI https://<bucket>.oss-us-west-1-internal.aliyuncs.com`
   — if the internal endpoint doesn't resolve, leave `OSS_INTERNAL_ENDPOINT` unset and
   uploads use the public endpoint (works; minor egress cost).

`.env` on the box (see `.env.example` for the full commented block):

```bash
CATALOG_ENABLED=1
POSTGRES_PASSWORD=<random>          # compose derives DATABASE_URL from it
OSS_ACCESS_KEY_ID=...               # the RAM user, never the account key
OSS_ACCESS_KEY_SECRET=...
OSS_BUCKET=dailies-catalog-<suffix>
OSS_INTERNAL_ENDPOINT=https://oss-us-west-1-internal.aliyuncs.com
```

Schema is Alembic-managed (`alembic/versions/`, autogenerated from
`server/db/models.py`); the app runs `upgrade head` automatically on its first successful
DB connection, so there is no manual migration step. By hand: `alembic upgrade head`.

Prove the OSS leg **before** relying on it (the Content-Disposition gate — post-2022
accounts force downloads on the default domain; our presigned URLs override to inline):

```bash
docker compose exec app python scripts/check_oss.py
# open the printed URL in a real browser: it must PLAY INLINE and SEEK, not download
```

Seed the catalog from existing local runs (the DB has no public port, so run it inside
the compose network):

```bash
docker compose exec app python scripts/seed_catalog.py --dry-run   # parse + report only
docker compose exec app python scripts/seed_catalog.py             # rows + OSS uploads
```

Verify:

```bash
curl http://<box-ip>/api/health              # -> "catalog":"ok"  ("off"|"unreachable")
curl http://<box-ip>/api/catalog/projects    # published runs
curl -i "http://<box-ip>/api/media/<a published clip path>"   # 302 -> presigned OSS URL
docker compose stop db                       # kill test: demo flow must still work,
                                             # health flips to "catalog":"unreachable"
docker compose start db
```

Warnings:

- **`docker compose down -v` destroys the `pgdata` volume** (the catalog DB). Plain
  `down`/`up` and redeploys are safe — the named volume persists.
- The `postgres:18` image mounts its volume at **`/var/lib/postgresql`** (not the old
  `.../data` path) — the compose file is already correct; don't "fix" it back.
- Presigned URLs are V4-signed: **box clock skew > ~15 min breaks every signature**
  (`timedatectl` to check). URLs are minted per request with a ~1 h TTL and never stored.

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
SPA is built inside the Docker `spa` stage. The deploy job's only job is SSH reach — the single
long-lived secret in GitHub is the deploy SSH key; `QWEN_API_KEY` never leaves the box.

**CI and CD are separate workflows.** `ci.yml` (the test suite) and `deploy-prod.yml` (this
deploy) trigger independently on push to `main`. A red CI does **not** block a deploy, and the
deploy job runs no tests — so a green deploy with a red CI is possible and means exactly what
it says: the box is serving, but the suite is unhappy. Watch both checks.

### Setup, in order

The one-time wiring, as executed on this box. The ssh lines assume a `~/.ssh/config` alias
`sas-qwen-hack` for the box (laptop-only — the runner can't read your ssh config, which is why
its `SERVER_HOST` secret takes the literal IP). Keep that literal IP out of every committed file;
it lives only in the secret and the `curl` in step 5, since this repo goes public.

**0. Provision the box.** An Alibaba Cloud [Simple Application Server](https://www.alibabacloud.com/help/en/simple-application-server/product-overview/what-is-simple-application-server)
with Docker + the compose plugin (an app image ships it preinstalled). Open **ports 80 and 22**
in the SAS firewall / security group. Deploying as a non-root user? Add it to the `docker` group
(`sudo usermod -aG docker $USER`, then re-login).

**1. Mint the CI key on your machine and prove it.** Never generate on the box: it receives only
the *public* half, while GitHub Actions — the SSH client here — holds the private half. Write the
key to `~/.ssh/`, not into this repo, where a stray `git add -A` could publish it.
```bash
ssh-keygen -t ed25519 -C "qwen-hack-2026-ci" -f ~/.ssh/qwen-hack-2026-ci -N ""
ssh-copy-id -i ~/.ssh/qwen-hack-2026-ci.pub sas-qwen-hack          # authenticates with the SAS password, once
ssh -i ~/.ssh/qwen-hack-2026-ci -o IdentitiesOnly=yes sas-qwen-hack 'echo key-auth-ok'
```
`ssh-copy-id` uses the SAS password you already have and appends the public key to the box's
`authorized_keys` — no sshd change, since `PubkeyAuthentication` is on by default. The third line
is the one that matters, and `IdentitiesOnly=yes` is load-bearing: plain `ssh -i` merely *adds*
the named key to the identities it offers, so an already-authorized `~/.ssh/id_ed25519` can print
`key-auth-ok` while the CI key was never accepted — a green test masking a credential CI will be
rejected with. The flag forces one key and no agent, exactly the runner's situation, so the test
proves what CI will actually experience.

**2. Register the secrets against the `production` environment** — not the repo, because
`SERVER_USER` is `root`, so only a job declaring `environment: production` should read them. Feed
the key from the file with `<`, never paste it — a mangled newline is the most common handshake
failure.
```bash
gh secret set SERVER_SSH_KEY --env production --repo Zen-cronic/qwen-hack-2026 < ~/.ssh/qwen-hack-2026-ci
gh secret set SERVER_HOST    --env production --repo Zen-cronic/qwen-hack-2026 --body "<sas-public-ip>"
gh secret set SERVER_USER    --env production --repo Zen-cronic/qwen-hack-2026 --body "root"
gh variable set ENV_NAME     --env production --repo Zen-cronic/qwen-hack-2026 --body "prod"   # optional; the script defaults to prod
gh secret list               --env production --repo Zen-cronic/qwen-hack-2026    # expect SERVER_HOST / SERVER_USER / SERVER_SSH_KEY
```
`ENV_NAME` is the hook for a future `dev`/`staging` box (copy the workflow, point it at another
host). For a manual release gate, turn on **Settings → Environments → production → Required
reviewers**.

**3. Clone the repo onto the box and seed its secrets** (once — CD never rewrites `.env`). While
the repo is private, clone with a fine-grained GitHub **PAT** (Repository access: this repo;
**Contents: read**, **Metadata: read**); once it flips public an anonymous clone works and future
`git fetch` needs no token.
```bash
git clone https://oauth2:${GITHUB_TOKEN}@github.com/Zen-cronic/qwen-hack-2026.git ~/dailies
cd ~/dailies && cp .env.example .env    # paste QWEN_API_KEY; set JUDGE_MODE / DAILIES_DEMO as desired
```
(The token in the remote URL persists in `~/dailies/.git/config`; use a git credential helper if
that matters.)

**4. Deploy and watch** (no commit needed — the workflow has `workflow_dispatch`):
```bash
gh workflow run deploy-prod.yml --repo Zen-cronic/qwen-hack-2026
gh run watch --repo Zen-cronic/qwen-hack-2026
```
First time only, you can instead run it by hand on the box: `chmod +x deploy/deploy-prod.sh &&
./deploy/deploy-prod.sh`.

**5. Confirm live, then seed the replay cache** so judge runs replay real footage for free
instead of spending the scarce t2v/i2v quota — `data/` is gitignored, so a fresh clone
arrives empty.
```bash
curl http://<sas-public-ip>/api/health      # -> {"status":"ok","mode":"real"}
rsync -avz ./data/cache/ sas-qwen-hack:/root/dailies/data/cache/     # ~81 MB, 33 clips
```

> **Small-tier boxes (≤2 GiB RAM) need swap before step 4**, or the on-box SPA build (npm ci +
> vite) can OOM-kill nginx/sshd during a re-deploy (which builds while the old container is still
> resident). Not needed after the 8 GB upgrade — see "After a plan upgrade". If you do need it:
> `sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo
> swapon /swapfile`, then add `/swapfile none swap sw 0 0` to `/etc/fstab`.

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

Read the failure by **duration** — it separates the three causes faster than the log text does.

- **Under 10 s, log ends `Error: missing server host`** — the secrets were never registered (step
  2): one or more of `SERVER_HOST`/`SERVER_USER`/`SERVER_SSH_KEY` is absent, so the action aborts
  before opening a connection. A near-instant death is always missing configuration, and no amount
  of workflow-file editing fixes it. Check with `gh secret list --env production`; note that a
  secret set at the *repo* level while the job reads the *environment* looks identical to an
  unset one — an unreadable secret interpolates to an empty string rather than erroring.
- **~30 s, `ssh: handshake failed` / `unable to authenticate`** — reached the box, credential
  rejected. Either the public half was never appended to the box's `~/.ssh/authorized_keys`, or
  the PEM lost its newlines on the way into the secret. Re-run the step-1 key check (`ssh -i
  ~/.ssh/qwen-hack-2026-ci -o IdentitiesOnly=yes sas-qwen-hack 'echo key-auth-ok'`); if that
  passes from your laptop, the paste is the suspect, so re-set the secret from the file with
  `gh secret set ... < ~/.ssh/qwen-hack-2026-ci`.
- **Minutes, dying at the health gate** — authentication was fine; the build broke or the app
  container never reported `healthy`. The action prints `docker compose logs` for exactly this.

## After a plan upgrade — extend the system disk

A SAS **plan upgrade** (e.g. to 4 vCPU / 8 GB / 70 GB) keeps the instance's IP and expiry
unchanged — so nothing about the deploy, the `SERVER_HOST` secret, or the judges' link moves.
RAM and vCPU take effect on the upgrade reboot with no action. The **one manual step** is the
system disk: the upgrade grows the cloud disk allocation, but the partition and filesystem
inside the OS were sized for the old disk and don't stretch on their own. Until you extend them,
`df -h /` still shows the old size while `lsblk` shows the disk itself at the new size.

Order is fixed: **partition first, filesystem second** — a filesystem can't grow past the
partition containing it, so resizing the filesystem first just no-ops. All of it is **online**:
no unmount, no downtime, the live URL keeps serving throughout.

1. **Confirm the gap and the filesystem type:**
   ```bash
   df -hT /      # TYPE column decides the step-3 tool; note which device is mounted at /
   lsblk         # the disk (vda) shows the NEW size; its partition still shows the old one
   ```
   If the disk itself (`vda`) still shows the old size, reboot once so the kernel re-reads it.

2. **Grow the partition.** The device and partition number are **separate, space-separated**
   arguments (`/dev/vda` and `1`), not `/dev/vda1` — the #1 growpart mistake. Substitute
   whatever `lsblk`/`df` showed mounted at `/`:
   ```bash
   sudo dnf install -y cloud-utils-growpart    # RHEL-family: dnf. There is no apt-get here.
   sudo growpart /dev/vda 1
   ```

3. **Grow the filesystem to fill the partition** — match the TYPE from step 1:
   ```bash
   sudo resize2fs /dev/vda1        # ext4 / ext3 (this box) — takes the DEVICE
   # sudo xfs_growfs /             # XFS instead — takes the MOUNTPOINT, not the device
   ```

4. **Verify:**
   ```bash
   df -h /       # now ~70 GB
   ```

**Distro note (this box).** `/etc/os-release` reports `ID=alinux`, `ID_LIKE="rhel fedora centos
anolis"`, `PLATFORM_ID=platform:al8` — **Alibaba Cloud Linux 3, RHEL 8-compatible** (Alibaba's
downstream of the OpenAnolis community CentOS replacement). It is RPM-based with **no `apt-get`**;
use `dnf` (`yum` is aliased to it). This is why the install above is `cloud-utils-growpart` via
`dnf`, not the Debian `cloud-guest-utils`.

The extra space lands where the deploy actually grows: `/var/lib/docker` (image layers, trimmed
by `docker image prune -f` each deploy but still churning) and `./data` (the replay cache + run
state) both live on `/`.

## Eligibility (manual, do on the box)

1. Bring the stack up and confirm the public URL loads.
2. **Capture the Alibaba Cloud Workbench screenshot** showing the running SAS resources —
   this is a mandatory judging gate ("No proof = not eligible"). Save it into the repo/blog.
3. Keep the URL live and unrestricted through the judging period.
