# Staging environment

A production-shaped copy of Audity that runs on your own machine. It exists so a
change can be proved before anyone outside sees it. Nothing here can reach
production.

## Why

Until now this project had two environments: local development with `DEBUG=True`
and everything relaxed, and production. That meant a whole class of problem had
nowhere to show up except in front of users. All of the following shipped to
production and were found there:

- A missing CORS origin (`http://tauri.localhost`) that silently broke desktop
  sign-in. Development never saw it, because development allows those origins.
- A rate limit that emptied the navigation bar once a real session made enough
  requests. Development had throttling effectively off.
- A static-file manifest lookup that only exists when `DEBUG=False`.
- Migrations that a deploy did not actually apply, with nothing downstream
  noticing until the schema and the code had drifted apart.

Staging keeps every production behaviour that can bite you and relaxes only what
a plain-HTTP localhost stack physically cannot do (TLS redirects, `Secure`
cookies). If a change survives staging, the remaining risk is infrastructure, not
the application.

## What it is made of

| Piece | Where | Notes |
|---|---|---|
| Django API | `http://localhost:8001` | gunicorn, `config.settings.staging`, `DEBUG=False` |
| PostgreSQL | `localhost:5433` | database `audity_staging`, its own volume |
| Redis | `localhost:6380` | its own volume |
| Celery worker | container `audity-staging-worker-1` | |
| Celery beat | container `audity-staging-beat-1` | the scheduled jobs finally have somewhere to fire other than production |
| Frontend (web) | `http://localhost:5174` | `npm run dev:staging` |
| Frontend (desktop) | installs as "Audity Staging" | `npm run tauri:build:staging` |

Every port is deliberately different from the development stack (8000, 3000,
5432, 6379), so the two can run side by side and you can never point `psql` at
the wrong database out of habit. Every Docker volume is prefixed
`audity-staging_`, so resetting staging cannot touch development data.

## Getting started

```bash
./scripts/staging.sh up      # build, start, wait until the API is healthy
./scripts/staging.sh seed    # load a demo company with real-looking data
```

Then, in a second terminal:

```bash
cd frontend
npm run dev:staging          # http://localhost:5174
```

Sign in with any of the seeded accounts. The seed command generates the password
and prints it once, so no working credential is ever written down in this repo.
Re-run `seed` if you lose it, or set `STAGING_SEED_PASSWORD` in your own
`.env.staging` to pin one:

| Role | Email |
|---|---|
| owner | `staging.owner@audity.test` |
| manager | `staging.manager@audity.test` |
| accountant | `staging.accountant@audity.test` |
| staff | `staging.staff@audity.test` |

Four roles, because most permission bugs only appear when you are not the owner.

## Commands

```bash
./scripts/staging.sh up            # start (builds if needed)
./scripts/staging.sh restart       # pick up a backend code change
./scripts/staging.sh down          # stop, keep the data
./scripts/staging.sh status        # what is running, is the API healthy
./scripts/staging.sh logs api      # follow logs: api | worker | beat | db | redis
./scripts/staging.sh seed          # load the demo company
./scripts/staging.sh fresh         # reset, start, seed: a clean slate
./scripts/staging.sh reset         # DELETE the staging database and volumes (asks first)
./scripts/staging.sh manage <cmd>  # any manage.py command inside the container
./scripts/staging.sh shell         # Django shell against the staging database
./scripts/staging.sh psql          # psql against the staging database
./scripts/staging.sh test          # pytest against the staging database (slow, see below)
./scripts/staging.sh rebuild       # rebuild images after a dependency change
```

`backend/` is mounted into the container, so a code change needs only
`./scripts/staging.sh restart`, which takes a second or two. You only need
`rebuild` when `backend/requirements/` changes.

gunicorn deliberately does not run with `--reload`. Production does not use it
either, and the point of staging is to be shaped like production.

## What it will not do, on purpose

These are guards, not defaults. Each one closes an accident that would otherwise
be silent.

**It will not start against a hosted database.** `staging.py` refuses any
`DB_HOST` that looks like RDS, Railway, Supabase, Neon, Render or DigitalOcean.
The worst thing this environment could do is write test invoices into a
customer's books, and that failure would not raise an error, it would just be
wrong. Override with `STAGING_ALLOW_REMOTE_DB=True` only if you genuinely mean
it.

**It will not send email.** Everything goes to the container log unless you set
`STAGING_ALLOW_REAL_EMAIL=True`. Seeded records contain email addresses, and a
test run that mails them has consequences outside your machine.

**It will not write to production object storage.** Uploads go to a local Docker
volume. `USE_S3` is ignored.

**It will not report to the production Sentry project.** Only
`STAGING_SENTRY_DSN` is read. Staging exists to produce errors; they must not
page anyone.

**The seed command will not run anywhere else.** `seed_staging` aborts unless
`settings.IS_STAGING` is true, which only `config.settings.staging` sets. Every
seeded address is on a `.test` domain, which RFC 2606 reserves and nothing
routes, so no mail can reach a seeded account even if email were switched on.

## What is seeded, and what is not

Seeded: one organisation, the full chart of accounts, four users at four roles,
a default warehouse, five product categories, fourteen products (some with
opening stock, some deliberately at zero so the low-stock and out-of-stock paths
have something to show), eight customers and five suppliers.

Not seeded: invoices, bills, payments and journals. Those are the thing under
test. Create them through the UI or the API so the posting logic, the GL mapping
and the permission checks actually run. Rows inserted straight into the database
would never have gone through the code path you care about, and a screen that
looks right on top of them proves nothing.

## Where this sits in the release flow

```
feature branch  ->  staging  ->  pull request  ->  main  ->  production
```

Work does not start on `main` and is not pushed there directly. A change is
built on a branch, proved against this staging stack, and reaches `main` only
through a reviewed pull request. Pushing a version tag is a separate, deliberate
act, because that triggers the release build that ships installers to users.

## Secrets

`./scripts/staging.sh up` creates `.env.staging` on first run and generates a
fresh `SECRET_KEY`, `FIELD_ENCRYPTION_KEY` and `DB_PASSWORD` into it. That file
is gitignored and is yours alone. `.env.staging.example` is committed and holds
only placeholders.

Do not copy production's `.env` here. Apart from being unnecessary, the two
staging secrets are meant to differ from production's, and a copied file would
fail the start-up guards anyway.

## Troubleshooting

**The API never becomes healthy.** Read the log: `./scripts/staging.sh logs api`.
The first start runs every migration and takes a few minutes. A start-up guard
failure appears as an `ImproperlyConfigured` message naming the exact setting.

**Port already in use.** Something else holds 8001, 5433, 6380 or 5174. The
development stack uses 8000, 5432, 6379 and 3000, so it is not the cause; check
for an older staging stack with `docker ps -a`.

**Login succeeds then immediately signs out.** Almost always a missing entry in
`CORS_ALLOWED_ORIGINS` in `.env.staging`. This is the bug staging exists to
catch, so read it as the environment working.

**A change in `backend/` has no effect.** Run
`./scripts/staging.sh restart`. There is no automatic reload, on purpose. Use
`rebuild` if you changed dependencies.

**`test` is slow.** The staging image is built from `requirements/production.txt`
and has no pytest in it, on purpose: adding test tools to the long-lived API
container would make it drift from the image production runs. So `test` spins up
a throwaway container, installs the development requirements there and runs
pytest against the staging database. For the quick inner loop use the repo's own
runner natively instead, and always with `--no-fix`, because a default run
reformats the whole backend:

```bash
python run_tests.py --no-fix
```
