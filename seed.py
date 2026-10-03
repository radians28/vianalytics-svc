"""Seed initial data (e.g. the default admin user).

Usage:
    ./.venv/bin/python seed.py

Admin credentials come from SEED_ADMIN_EMAIL / SEED_ADMIN_PASSWORD (environment
or .env).
"""
import os
import sys

from werkzeug.security import generate_password_hash

from app import create_app
from app.common.helpers import jakarta_now
from app.extensions import db
from app.models.team_member import TeamMember

# Importing `app` above already loaded .env (see app/config.py).
ADMIN_EMAIL = os.environ.get("SEED_ADMIN_EMAIL", "admin@admin.com")
ADMIN_PASSWORD = os.environ.get("SEED_ADMIN_PASSWORD")
ADMIN_ROLE = "admin"


def seed_admin():
    existing = TeamMember.query.filter_by(user_email=ADMIN_EMAIL).first()
    if existing:
        print(f"Admin user '{ADMIN_EMAIL}' already exists, skipping.")
        return

    admin = TeamMember()
    admin.user_email = ADMIN_EMAIL
    admin.password = generate_password_hash(ADMIN_PASSWORD)
    admin.user_first_name = "Admin"
    admin.user_last_name = "User"
    admin.user_role = ADMIN_ROLE
    admin.verified_at = jakarta_now()  # required for login_member's verified_at filter

    db.session.add(admin)
    db.session.commit()
    print(f"Seeded admin user '{ADMIN_EMAIL}'.")


if __name__ == "__main__":
    if not ADMIN_PASSWORD:
        sys.exit("SEED_ADMIN_PASSWORD is not set; define it in the environment or .env")

    app = create_app()
    with app.app_context():
        seed_admin()
