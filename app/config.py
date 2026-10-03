import os

from dotenv import load_dotenv

from app.common.helpers import APP_TIMEZONE

# Load variables from .env (if present); real environment variables take precedence.
load_dotenv()

_database_url = os.environ.get(
    "DATABASE_URL",
    "sqlite:///" + os.path.join(os.getcwd(), "app.db"),
)

_engine_options = {
    "pool_pre_ping": True,  # avoids stale connections on long-lived pools
}
if _database_url.startswith("postgresql"):
    # Make Postgres return timestamptz values (and evaluate now()/::date) in
    # Jakarta time, whatever the DB server's own timezone is.
    _engine_options["connect_args"] = {"options": f"-c timezone={APP_TIMEZONE}"}


class Config:
    SQLALCHEMY_DATABASE_URI = _database_url
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = _engine_options

    # Secret used to sign/verify JWT access tokens. Required.
    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY")

    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50 MB upload cap
    UPLOAD_FOLDER = os.environ.get(
        "UPLOAD_FOLDER",
        os.path.join(os.getcwd(), "uploaded_files")
    )

    # Comma-separated list of origins allowed to call this API cross-origin,
    # e.g. "http://localhost:5173,https://app.vianalytics.com"
    CORS_ORIGINS = [
        origin.strip()
        for origin in os.environ.get("CORS_ORIGINS", "*").split(",")
        if origin.strip()
    ]

    # Timezone for cron schedules; defaults to Jakarta, like the rest of the app
    CRON_TIMEZONE = os.environ.get("CRON_TIMEZONE") or APP_TIMEZONE
