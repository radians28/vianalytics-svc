#!/bin/sh
# Container entrypoint. SVC_ROLE picks what this container runs:
#   api     - API server (default; scale freely with GUNICORN_WORKERS / replicas)
#   migrate - apply DB migrations and seed initial data, then exit
# RUN_MIGRATIONS=1 applies migrations (then seeding) before starting the API.
# Scheduled jobs run in Airflow (vianalytics-infra), not in this service.
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

case "${SVC_ROLE:-api}" in
    api)
        [ "${RUN_MIGRATIONS:-0}" = "1" ] && migrate
        run_api
        ;;
    migrate)
        migrate
        ;;
    *)
        echo "Unknown SVC_ROLE '${SVC_ROLE}' (expected api|migrate)" >&2
        exit 64
        ;;
esac
