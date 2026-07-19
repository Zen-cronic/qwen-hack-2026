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
  fresh-clip cap per session — 2 drafts and 2 premium promotions (`server/budget.py`);
  cached replays are free and uncapped. Past the cap the run still completes: the passing
  draft is certified in place of the premium final. Watch the judge-reserve quota.
  Pay-as-you-go must stay enabled in the Model Studio console ("Stop When Free Quota Is
  Used Up" **off**), or voucher credit can't be spent and billable calls hard-fail once
  the per-model free grant runs out.
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
SPA is built inside the Docker `spa` stage. The deploy job's only job is SSH reach — the single
long-lived secret in GitHub is the deploy SSH key; `QWEN_API_KEY` never leaves the box.

**CI and CD are separate workflows.** `ci.yml` (the test suite) and `deploy-prod.yml` (this
deploy) trigger independently on push to `main`. A red CI does **not** block a deploy, and the
deploy job runs no tests — so a green deploy with a red CI is possible and means exactly what
it says: the box is serving, but the suite is unhappy. Watch both checks.

### Quick sequence (this box, in order)

The exact path this deployment took — CD via GitHub Actions, key-only auth, secrets scoped to
the `production` environment. The ssh commands assume a `~/.ssh/config` alias `sas-qwen-hack`
for the box (laptop-only; CI can't read your ssh config, so its secret uses the literal IP).
Each step's *why* is in "One-time setup" below; this is the command record.

**On your machine — mint the CI key and prove it** (never generate on the box: it receives only
the public half, and GitHub Actions is the SSH *client* that holds the private half):
```bash
ssh-keygen -t ed25519 -C "qwen-hack-2026-ci" -f ~/.ssh/qwen-hack-2026-ci -N ""
ssh-copy-id -i ~/.ssh/qwen-hack-2026-ci.pub sas-qwen-hack          # authenticates with the SAS password, once
ssh -i ~/.ssh/qwen-hack-2026-ci -o IdentitiesOnly=yes sas-qwen-hack 'echo key-auth-ok'
```
`IdentitiesOnly=yes` is load-bearing on that last line. Plain `ssh -i <key>` *adds* the named
key to the identities it offers rather than restricting to it, so an already-authorized
`~/.ssh/id_ed25519` can answer the challenge and print `key-auth-ok` while the CI key was never
accepted — a green test hiding a credential CI will be rejected with. The flag forces ssh to
offer only this one key with no agent, which is exactly the runner's situation, so the test now
proves what CI will actually experience.

**Register the secrets against the `production` environment** (not the repo — `SERVER_USER` is
`root`, so only a job declaring `environment: production` should read them):
```bash
gh secret set SERVER_SSH_KEY --env production --repo Zen-cronic/qwen-hack-2026 < ~/.ssh/qwen-hack-2026-ci
gh secret set SERVER_HOST    --env production --repo Zen-cronic/qwen-hack-2026 --body "<sas-public-ip>"
gh secret set SERVER_USER    --env production --repo Zen-cronic/qwen-hack-2026 --body "root"
gh variable set ENV_NAME     --env production --repo Zen-cronic/qwen-hack-2026 --body "prod"   # optional; the script defaults to prod
gh secret list               --env production --repo Zen-cronic/qwen-hack-2026    # expect SERVER_HOST / SERVER_USER / SERVER_SSH_KEY
```
Feed the key from the file with `<`, never paste it — a mangled newline is the most common
handshake failure. Keep the literal `<sas-public-ip>` out of every committed file; it lives only
in the `SERVER_HOST` secret and the `curl` below (this repo goes public).

**On the box — size it, clone it, seed its secret** (once):
```bash
# Small-tier only (<=2 GiB RAM): add swap so the on-box SPA build (npm ci + vite) can't
# OOM-kill nginx/sshd during a re-deploy, which builds while the old container is resident.
# NOT needed after the 8 GB plan upgrade (see "After a plan upgrade") -- the build fits in RAM.
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
git clone https://oauth2:${GITHUB_TOKEN}@github.com/Zen-cronic/qwen-hack-2026.git ~/dailies   # PAT while private
cd ~/dailies && cp .env.example .env    # paste QWEN_API_KEY; set JUDGE_MODE / DAILIES_DEMO as desired
```

**Trigger the deploy and watch it** (no commit needed — the workflow has `workflow_dispatch`):
```bash
gh workflow run deploy-prod.yml --repo Zen-cronic/qwen-hack-2026
gh run watch --repo Zen-cronic/qwen-hack-2026
```

**Confirm it's live, then seed the replay cache** so judge runs replay real footage for free
instead of spending the nearly-exhausted premium quota:
```bash
curl http://<sas-public-ip>/api/health      # -> {"status":"ok","mode":"real"}
rsync -avz ./data/cache/ sas-qwen-hack:/root/dailies/data/cache/     # ~81 MB, 33 clips; data/ is gitignored so a clone arrives empty
```

### One-time setup

1. **SAS instance + Docker.** Provision an Alibaba Cloud [Simple Application
   Server](https://www.alibabacloud.com/help/en/simple-application-server/product-overview/what-is-simple-application-server)
   (an app image with Docker preinstalled, or install Docker + the compose plugin yourself).
   Open **port 80** (and **22** for SSH) in the SAS firewall / security group. If you deploy as
   a non-root user, add it to the `docker` group (`sudo usermod -aG docker $USER`, re-login).

2. **Dedicated CI key.** SAS instances are provisioned with a root password and password login
   enabled, so the box is reachable before any of this — but the deploy authenticates by key.
   A key is scoped to this pipeline, revocable by deleting one line on the box, and useless to
   anyone who can't also present the private half; the login password is none of those things.

   **Run these on your own machine, not on the SAS box** — the box only ever receives the
   *public* half, and the private half goes to GitHub, because in this topology GitHub Actions
   is the SSH client:
   ```bash
   ssh-keygen -t ed25519 -C "qwen-hack-2026-ci" -f ~/.ssh/qwen-hack-2026-ci -N ""
   ssh-copy-id -i ~/.ssh/qwen-hack-2026-ci.pub <user>@<sas-public-ip>   # prompts for the SAS password
   ssh -i ~/.ssh/qwen-hack-2026-ci -o IdentitiesOnly=yes <user>@<sas-public-ip> 'echo key-auth-ok'
   ```
   Write the key to `~/.ssh/`, **not** into this repo — an untracked private key in the working
   tree is one `git add -A` away from a public repository.

   `ssh-copy-id` authenticates with the SAS password you already have and appends the public key
   to the box's `~/.ssh/authorized_keys`, so this needs no sshd change — `PubkeyAuthentication`
   is on by default.

   The third command is the one that matters: it proves key auth works while the failure is
   still one line of shell to diagnose, rather than a red CI run. `IdentitiesOnly=yes` is not
   optional there — without it `ssh -i` merely *adds* the named key to the identities on offer,
   so an `id_ed25519` that already happens to be authorized can satisfy the test and hide a CI
   key the box never accepted. The flag reproduces the runner's conditions: one key, no agent.

3. **GitHub → Settings → Secrets and variables → Actions.**
   - Secrets: `SERVER_HOST` = SAS **public IP**, `SERVER_USER` = the SSH user (`root` or your deploy
     user), `SERVER_SSH_KEY` = the **private** key from step 2 (full PEM, header/footer lines
     included). Set them from the file rather than pasting — `gh secret set SERVER_SSH_KEY
     --env production < ~/.ssh/qwen-hack-2026-ci` — which sidesteps newline mangling.
   - Scope them to the **`production` environment**, not the repo, so only a job declaring
     `environment: production` can read them. `SERVER_USER` is `root`, so this is unrestricted
     root on the box; narrowing the readership is worth the extra flag.
   - `SERVER_HOST` takes the **literal IP**. A `~/.ssh/config` alias resolves only on your
     machine — the runner is a bare container with no config file, no agent, and no known_hosts.
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

Read the failure by **duration** — it separates the three causes faster than the log text does.

- **Under 10 s, log ends `Error: missing server host`** — step 3 was never done: one or more of
  `SERVER_HOST`/`SERVER_USER`/`SERVER_SSH_KEY` is absent, so the action aborts before opening a
  connection. A near-instant death is always missing configuration, and no amount of
  workflow-file editing fixes it. Check with `gh secret list --env production`; note that a
  secret set at the *repo* level while the job reads the *environment* looks identical to an
  unset one — an unreadable secret interpolates to an empty string rather than erroring.
- **~30 s, `ssh: handshake failed` / `unable to authenticate`** — reached the box, credential
  rejected. Either the public half was never appended to the box's `~/.ssh/authorized_keys`, or
  the PEM lost its newlines on the way into the secret. Re-run the step-2 verification command
  with `IdentitiesOnly=yes`; if that passes from your laptop, the paste is the suspect, so
  re-set the secret from the file with `gh secret set ... < ~/.ssh/qwen-hack-2026-ci`.
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
