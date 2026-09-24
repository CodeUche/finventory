#!/usr/bin/env bash
#
# Audity staging environment: one entry point for all of it.
#
# Staging is a production-shaped stack on this machine only: its own database,
# its own Redis, its own ports, its own secrets. It exists so a change can be
# proved before it reaches users, because main is not a testing environment.
#
# Usage:
#   ./scripts/staging.sh up          Build if needed, start everything, wait for health
#   ./scripts/staging.sh seed        Load a demo company with real-looking data
#   ./scripts/staging.sh fresh       reset + up + seed: a clean environment from nothing
#   ./scripts/staging.sh restart     Pick up a backend code change (a second or two)
#   ./scripts/staging.sh down        Stop the stack, keep the data
#   ./scripts/staging.sh reset       Stop and DELETE the staging database and volumes
#   ./scripts/staging.sh status      What is running, and is the API healthy
#   ./scripts/staging.sh logs [svc]  Follow logs (api, worker, beat, db, redis)
#   ./scripts/staging.sh manage ...  Run any manage.py command inside the API container
#   ./scripts/staging.sh shell       Django shell against the staging database
#   ./scripts/staging.sh psql        psql against the staging database
#   ./scripts/staging.sh test [args] Run tests against staging settings (slow: installs test deps)
#   ./scripts/staging.sh rebuild     Rebuild images after a dependency change
#
# Nothing here can touch production: no AWS credentials are used, no production
# hostname appears, and staging.py refuses to start against a hosted database.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$ROOT/docker-compose.staging.yml"
ENV_FILE="$ROOT/.env.staging"
ENV_TEMPLATE="$ROOT/.env.staging.example"
API_URL="http://localhost:8001/api/v1/health/"

say()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
note() { printf '    %s\n' "$*"; }
fail() { printf '\n\033[31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

# docker compose (v2) with a fallback to the old docker-compose binary.
dc() {
  if docker compose version >/dev/null 2>&1; then
    docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
  else
    docker-compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
  fi
}

require_docker() {
  docker info >/dev/null 2>&1 \
    || fail "Docker is not running. Start Docker Desktop and try again."
}

# ── .env.staging: created once, with real generated secrets ───────────────────
# The secrets are generated rather than templated so that no two machines share
# them and so that nothing in the repo ever contains a working key.
ensure_env() {
  [ -f "$ENV_FILE" ] && return 0
  [ -f "$ENV_TEMPLATE" ] || fail "Missing $ENV_TEMPLATE"

  say "First run: creating .env.staging with freshly generated secrets"
  local secret field dbpass
  secret="$(node -e 'console.log(require("crypto").randomBytes(48).toString("base64url"))')"
  field="$(node -e 'console.log(require("crypto").randomBytes(32).toString("base64url"))')"
  dbpass="$(node -e 'console.log(require("crypto").randomBytes(18).toString("base64url"))')"

  SECRET="$secret" FIELD="$field" DBPASS="$dbpass" \
  node -e '
    const fs = require("fs");
    let t = fs.readFileSync(process.argv[1], "utf8");
    t = t.replace(/^SECRET_KEY=.*$/m,           "SECRET_KEY=" + process.env.SECRET);
    t = t.replace(/^FIELD_ENCRYPTION_KEY=.*$/m, "FIELD_ENCRYPTION_KEY=" + process.env.FIELD);
    t = t.replace(/^DB_PASSWORD=.*$/m,          "DB_PASSWORD=" + process.env.DBPASS);
    fs.writeFileSync(process.argv[2], t);
  ' "$ENV_TEMPLATE" "$ENV_FILE"

  note "Wrote $ENV_FILE (gitignored). Edit it freely; it is yours, not production's."
}

wait_for_api() {
  say "Waiting for the API to report healthy"
  local tries=60
  while [ "$tries" -gt 0 ]; do
    if curl -fsS --max-time 5 "$API_URL" >/dev/null 2>&1; then
      note "API is up: http://localhost:8001"
      return 0
    fi
    tries=$((tries - 1))
    sleep 2
  done
  printf '\n\033[31mThe API did not come up in ~2 minutes.\033[0m\n' >&2
  note "Last 40 lines of the api log:"
  dc logs --tail 40 api || true
  return 1
}

cmd_up() {
  require_docker; ensure_env
  say "Starting the staging stack"
  dc up -d --build
  wait_for_api
  cmd_status
  cat <<'BANNER'

    Staging is ready.

      API        http://localhost:8001
      Admin      http://localhost:8001/admin/
      Postgres   localhost:5433   (audity_staging)
      Redis      localhost:6380

    Frontend against staging:
      cd frontend && npm run dev:staging       # http://localhost:5174

    No data yet? Load a demo company:
      ./scripts/staging.sh seed

BANNER
}

cmd_seed() {
  require_docker; ensure_env
  say "Seeding a demo company into staging"
  dc exec -T api python manage.py seed_staging
}

cmd_restart() {
  require_docker; ensure_env
  # --force-recreate, not `docker compose restart`. A plain restart reuses the
  # container's existing spec, so an edit to docker-compose.staging.yml is
  # silently ignored and you debug a change that was never applied. Recreating
  # costs a few seconds and covers both a code change and a config change.
  say "Recreating the API, worker and beat to pick up changes"
  dc up -d --force-recreate --no-deps api worker beat
  wait_for_api
}

cmd_down() {
  require_docker
  say "Stopping the staging stack (data kept)"
  dc down
}

cmd_reset() {
  require_docker
  say "This DELETES the staging database, Redis, media and static volumes"
  note "The dev stack (finventory-db-1) and production are not touched."
  printf '    Type "reset" to confirm: '
  local answer; read -r answer
  [ "$answer" = "reset" ] || fail "Not confirmed, nothing was deleted."
  dc down -v
  note "Staging volumes removed. Run './scripts/staging.sh up' for a clean stack."
}

cmd_fresh() {
  cmd_reset
  cmd_up
  cmd_seed
}

cmd_status() {
  require_docker
  say "Staging services"
  dc ps
  printf '\n'
  if curl -fsS --max-time 5 "$API_URL" >/dev/null 2>&1; then
    printf '    \033[32mAPI healthy\033[0m   %s\n' "$API_URL"
  else
    printf '    \033[31mAPI not responding\033[0m   %s\n' "$API_URL"
  fi
}

cmd_logs()    { require_docker; dc logs -f --tail 100 "${@:-api}"; }
cmd_manage()  { require_docker; dc exec -T api python manage.py "$@"; }
cmd_shell()   { require_docker; dc exec api python manage.py shell; }
cmd_psql()    {
  require_docker
  # shellcheck disable=SC1090
  set -a; . "$ENV_FILE"; set +a
  dc exec -e PGPASSWORD="$DB_PASSWORD" db psql -U "$DB_USER" -d "$DB_NAME"
}
cmd_rebuild() { require_docker; ensure_env; say "Rebuilding images"; dc build --no-cache; }

cmd_test() {
  require_docker; ensure_env
  # A throwaway container, not the running API. The staging image is built from
  # requirements/production.txt, which has no pytest, and installing test tools
  # into the long-lived API container would make it drift from the image
  # production actually runs. So: a fresh container, dev requirements installed
  # in it, torn down afterwards. It shares the staging database.
  #
  # This is the slow, production-shaped path. For the quick inner loop use the
  # repo's own runner natively, and always with --no-fix, because a default run
  # reformats the whole backend and buries unrelated work in progress:
  #     python run_tests.py --no-fix
  say "Running tests in a throwaway container against the staging database"
  note "Installing test dependencies first; this makes the run slower."
  # -u root because the image runs as the unprivileged `finventory` user with no
  # writable home or site-packages, so pip cannot install anything as itself.
  # Safe here only because the container is thrown away at the end of the run.
  dc run --rm --no-deps -u root -e HOME=/tmp -T api sh -c     "pip install --quiet --no-cache-dir -r requirements/development.txt &&      python -m pytest ${*:--q}"
}

case "${1:-}" in
  up)      shift; cmd_up "$@" ;;
  seed)    shift; cmd_seed "$@" ;;
  fresh)   shift; cmd_fresh "$@" ;;
  restart) shift; cmd_restart "$@" ;;
  down)    shift; cmd_down "$@" ;;
  reset)   shift; cmd_reset "$@" ;;
  status)  shift; cmd_status "$@" ;;
  logs)    shift; cmd_logs "$@" ;;
  manage)  shift; cmd_manage "$@" ;;
  shell)   shift; cmd_shell "$@" ;;
  psql)    shift; cmd_psql "$@" ;;
  test)    shift; cmd_test "$@" ;;
  rebuild) shift; cmd_rebuild "$@" ;;
  *)
    sed -n '3,30p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit 1
    ;;
esac
