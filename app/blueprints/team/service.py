from datetime import datetime, timezone, timedelta
from flask import abort
from sqlalchemy import select, asc, desc, func
from werkzeug.security import check_password_hash, generate_password_hash
import secrets
import string

from app.blueprints.team.requests.login_request import LoginRequest
from app.blueprints.team.requests.register_request import RegisterRequest
from app.blueprints.team.requests.verified_request import VerifiedRequest
from app.blueprints.team.requests.update_profile_request import UpdateProfileRequest
from app.blueprints.team.requests.change_password_request import ChangePasswordRequest
from app.blueprints.team.requests.change_role_request import ChangeRoleRequest

from app.common.helpers import (jakarta_now)
from app.common.token_handler import encode
from app.common.pagination_request import UserPaginationRequest, SortOrder
from app.extensions import db
from app.models.team_member import TeamMember

alphanumeric = string.ascii_letters + string.digits

def _issue_session(user: TeamMember) -> dict:
    """Build the same access_token/decoded_token pair for a user regardless
    of whether they got here via login or via completing verification."""
    payload = {
        'user_id': user.user_id,
        'user_email': user.user_email,
        'user_first_name': user.user_first_name,
        'user_last_name': user.user_last_name,
        'roles': [user.user_role],
        'exp': datetime.now(timezone.utc) + timedelta(hours=12),
        'iat': datetime.now(timezone.utc)
    }

    return {
        'access_token': encode(payload),
        'decoded_token': payload
    }

def get_team_members(request_body):
    statements = select(TeamMember)
    statements = statements.where(TeamMember.deactivated_at == None)

    if request_body.filter:
        for key, value in request_body.filter.items():
            match key:
                case 'user_email' | 'user_first_name' | 'user_last_name':
                    statements = statements.where(getattr(TeamMember, key).icontains(value))
                case 'user_role':
                    statements = statements.where(getattr(TeamMember, key) == value)

    count = db.session.execute(
        select(func.count()).select_from(statements.subquery())
    ).scalar_one()

    if request_body.sort:
        for column, order in request_body.sort.items():
            order_fn = asc if order == SortOrder.ASC else desc
            statements = statements.order_by(order_fn(getattr(TeamMember, column)))
    statements = statements.offset(request_body.offset).limit(request_body.size)
    records = db.session.execute(statements).scalars().all()

    return {
        'total_count': count,
        'records': [{
            'user_id': r.user_id,
            'user_email': r.user_email,
            'user_first_name': r.user_first_name,
            'user_last_name': r.user_last_name,
            'user_role': r.user_role,
            'verified_at': r.verified_at,
            'otp': r.otp_token
        } for r in records]
    }

def register_member(register_data: RegisterRequest) -> str:
    existing = db.session.execute(
        select(TeamMember).where(TeamMember.user_email == register_data.user_email)
    ).scalar_one_or_none()
    if existing:
        abort(400, description='Conflict member, already registered')

    new_member = TeamMember()
    new_member.user_email = register_data.user_email
    new_member.user_first_name = register_data.user_first_name
    new_member.user_last_name = register_data.user_last_name
    new_member.user_role = register_data.user_role
    new_member.otp_token = ''.join(secrets.choice(alphanumeric) for _ in range(48))

    db.session.add(new_member)
    db.session.commit()
    return new_member.otp_token

def check_otp_token(otp_token: str) -> dict:
    """Look up a member by their verification token alone (no user_id yet —
    the frontend only has the token from the verification link URL)."""
    if not otp_token:
        abort(404, description="Invalid or expired verification link")

    user = db.session.execute(
        select(TeamMember).where(TeamMember.otp_token == otp_token)
    ).scalar_one_or_none()

    if user is None:
        abort(404, description="Invalid or expired verification link")

    if user.verified_at is not None:
        abort(400, description="This account has already been verified")

    return {
        'user_id': user.user_id,
        'user_email': user.user_email,
        'user_first_name': user.user_first_name,
    }

def verified_user(verification: VerifiedRequest) -> dict:
    user = db.session.get(TeamMember, verification.user_id)

    # otp_token must actually match — previously this only checked user_id,
    # so anyone who saw a user_id (e.g. in the team list) could set a
    # password without ever having the real verification token.
    if not user or user.otp_token != verification.otp_token:
        abort(404, description="Credential is not valid")

    if user.verified_at is not None:
        abort(400, description="This account has already been verified")

    user.password = generate_password_hash(verification.password)
    user.verified_at = jakarta_now()
    user.otp_token = None

    db.session.commit()

    # Same shape as login's response, so completing verification can log the
    # user straight into the app without a separate login step.
    return _issue_session(user)

def update_profile(user_id: str, data: UpdateProfileRequest) -> dict:
    user = db.session.get(TeamMember, user_id)
    if not user:
        abort(404, description="User not found")

    user.user_first_name = data.user_first_name
    user.user_last_name = data.user_last_name
    db.session.commit()

    # The name is baked into the JWT (decoded_token), so the client needs a
    # freshly-issued token to reflect the change without re-logging in.
    return _issue_session(user)

def change_password(user_id: str, data: ChangePasswordRequest):
    user = db.session.get(TeamMember, user_id)
    if not user or not check_password_hash(user.password, data.current_password):
        abort(400, description="Current password is incorrect")

    user.password = generate_password_hash(data.new_password)
    db.session.commit()

def change_member_role(actor_user_id: str, target_user_id: str, data: ChangeRoleRequest) -> dict:
    if actor_user_id == target_user_id:
        abort(400, description="You cannot change your own role")

    user = db.session.get(TeamMember, target_user_id)
    if not user:
        abort(404, description="User not found")

    user.user_role = data.user_role
    db.session.commit()

    return {
        'user_id': user.user_id,
        'user_email': user.user_email,
        'user_first_name': user.user_first_name,
        'user_last_name': user.user_last_name,
        'user_role': user.user_role,
    }

def delete_member(actor_user_id: str, target_user_id: str):
    if actor_user_id == target_user_id:
        abort(400, description="You cannot delete your own account")

    user = db.session.get(TeamMember, target_user_id)
    if not user:
        abort(404, description="User not found")

    user.deactivated_at = jakarta_now()
    db.session.commit()

def login_member(login_data: LoginRequest) -> dict:
    statement = select(TeamMember).where(TeamMember.user_email == login_data.user_email)
    statement = statement.where(TeamMember.verified_at != None)
    statement = statement.where(TeamMember.deactivated_at == None)
    user = db.session.execute(statement).scalar_one_or_none()

    if user is None or not check_password_hash(user.password, login_data.password):
        abort(404, description=f"Credential is not valid")

    return _issue_session(user)