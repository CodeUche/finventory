# GitHub Secrets Setup Guide

All secrets are configured at **Settings → Secrets and variables → Actions** in your GitHub repository.

---

## Required Secrets

### Backend Deployment (Railway)

| Secret | How to get it |
|---|---|
| `RAILWAY_TOKEN` | Railway dashboard → Project → Settings → Tokens → New token |
| `RAILWAY_BACKEND_SERVICE` | The exact service name shown in your Railway dashboard (e.g. `audity-backend`) |

### Frontend (Tauri Desktop Build)

| Secret | How to get it |
|---|---|
| `VITE_API_BASE_URL` | Your production API base URL (e.g. `https://api.audity.com`) |
| `TAURI_SIGNING_PRIVATE_KEY` | See "Generating Tauri signing keys" below |
| `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` | Passphrase you chose when generating the key |

> **Note:** `TAURI_SIGNING_PRIVATE_KEY` and `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` are only needed
> if you enable Tauri's auto-update feature. The build will succeed without them.

---

## Generating Tauri Signing Keys

Run this once on your local machine:

```bash
cd "c:/Dev Projects/FinTax App/finventory/frontend"
npm run tauri signer generate -- -w ~/.tauri/audity.key
```

This outputs:
- `~/.tauri/audity.key` — **private key** (base64) → paste as `TAURI_SIGNING_PRIVATE_KEY`
- `~/.tauri/audity.key.pub` — public key → add to `tauri.conf.json` under `plugins.updater.pubkey`

Keep the private key file off your machine after copying it into GitHub Secrets.

---

## Setting Up the `production` Environment

The `deploy-backend` job uses `environment: production`, which unlocks:
- **Required reviewers** — force a human approval before every production deploy
- **Wait timer** — add a delay (e.g. 5 min) to allow cancellation

To configure: **Settings → Environments → production → Protection rules**

Recommended settings:
- ✅ Required reviewers: add yourself (and team leads)
- ✅ Restrict to `main` branch only
- ✅ Wait timer: 0–5 minutes

---

## Railway Environment Variables (set in Railway dashboard)

These must be set on your Railway backend service — not in GitHub:

```
SECRET_KEY=<generate with: python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())">
DEBUG=False
DJANGO_SETTINGS_MODULE=config.settings.production
ALLOWED_HOSTS=api.audity.com,*.railway.app
DB_NAME=<from Railway PostgreSQL plugin>
DB_USER=<from Railway PostgreSQL plugin>
DB_PASSWORD=<from Railway PostgreSQL plugin>
DB_HOST=<from Railway PostgreSQL plugin>
DB_PORT=5432
REDIS_URL=<from Railway Redis plugin>
ADMIN_URL=<random string, e.g. xk9p2qm3-admin/>
USE_S3=True
AWS_ACCESS_KEY_ID=<Cloudflare R2 or AWS>
AWS_SECRET_ACCESS_KEY=<Cloudflare R2 or AWS>
AWS_STORAGE_BUCKET_NAME=audity-media
AWS_S3_ENDPOINT_URL=<R2 endpoint or blank for AWS>
CORS_ALLOWED_ORIGINS=https://app.audity.com
```

---

## Triggering a GitHub Release

Push a version tag to create a release with both Windows installers attached:

```bash
git tag v1.0.0
git push origin v1.0.0
```

Pre-release tags (marked as pre-release on GitHub):
```bash
git tag v1.0.0-beta.1
git push origin v1.0.0-beta.1
```
