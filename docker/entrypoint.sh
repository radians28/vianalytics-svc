#!/bin/sh
# Container entrypoint. SVC_ROLE picks what this container runs:
#   all     - API + cron in one container (default; one replica only, or
#             cron jobs run once per replica)
#   api     - API only (scale freely with GUNICORN_WORKERS / replicas)
#   cron    - cron worker only (run exactly one)
#   migrate - apply DB migrations and seed initial data, then exit
# RUN_MIGRATIONS=1 applies migrations (then seeding) before starting api/all.
set -e

run_api() {
    exec gunicorn run:app \
        --bind "0.0.0.0:${PORT:-3000}" \
        --workers "${GUNICORN_WORKERS:-2}" \
        --threads "${GUNICORN_THREADS:-4}" \
        --timeout "${GUNICORN_TIMEOUT:-120}" \
        --access-logfile - \
        --error-logfile -
}

migrate() {
    echo "Applying database migrations..."
    flask db upgrade
    # Idempotent: seed.py skips the admin if that email already exists
    if [ -n "${SEED_ADMIN_PASSWORD:-}" ]; then
        echo "Seeding initial data..."
        python seed.py
    else
        echo "SEED_ADMIN_PASSWORD not set; skipping seeding"
    fi
}

case "${SVC_ROLE:-all}" in
    api)
        [ "${RUN_MIGRATIONS:-0}" = "1" ] && migrate
        run_api
        ;;
    cron)
        exec python cron.py
        ;;
    migrate)
        migrate
        ;;
    all)
        [ "${RUN_MIGRATIONS:-0}" = "1" ] && migrate
        # Cron runs in the background; gunicorn stays PID 1's child in the
        # foreground. If either one dies, stop the other so the container
        # exits and the restart policy brings both back together.
        python cron.py &
        cron_pid=$!
        run_api &
        api_pid=$!

        stopping=0
        trap 'stopping=1; kill -TERM "$api_pid" "$cron_pid" 2>/dev/null' TERM INT
        while kill -0 "$api_pid" 2>/dev/null && kill -0 "$cron_pid" 2>/dev/null; do
            sleep 1
        done
        kill -TERM "$api_pid" "$cron_pid" 2>/dev/null || true
        wait
        [ "$stopping" = "1" ] && exit 0
        echo "API or cron process exited unexpectedly; stopping container" >&2
        exit 1
        ;;
    *)
        echo "Unknown SVC_ROLE '${SVC_ROLE}' (expected all|api|cron|migrate)" >&2
        exit 64
        ;;
esac
