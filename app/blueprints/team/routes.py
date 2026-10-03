import json
from flask import Blueprint, g, request, current_app
from pydantic import ValidationError
from werkzeug.exceptions import HTTPException

from app.blueprints.team.requests.login_request import LoginRequest
from app.blueprints.team.requests.register_request import RegisterRequest
from app.blueprints.team.requests.verified_request import VerifiedRequest
from app.blueprints.team.requests.update_profile_request import UpdateProfileRequest
from app.blueprints.team.requests.change_password_request import ChangePasswordRequest
from app.blueprints.team.requests.change_role_request import ChangeRoleRequest
from app.blueprints.team.service import (
    get_team_members,
    register_member,
    login_member,
    verified_user,
    check_otp_token,
    update_profile,
    change_password,
    change_member_role,
    delete_member,
)
from app.common.decorators.role_decorator import roles
from app.common.helpers import (
    success_response,
    error_response,
)
from app.common.logger import get_logger
from app.common.pagination_request import UserPaginationRequest

route = Blueprint('team', __name__)
logger = get_logger(__name__)

@route.post('')
@roles('admin')
def get_team():
    json_data = request.get_json()

    try:
        request_body = UserPaginationRequest(**json_data)
        results = get_team_members(request_body)
        return success_response(results)
    except ValidationError as e:
        logger.exception(f"Unexpected system crash. Details: {e}")
        return error_response('Request to register member is not valid')
    except HTTPException as e:
        return error_response(e.description or 'Something went wrong', code=e.code or 500)
    except Exception as e:
        logger.exception(f"Unexpected system crash. Details: {e}")
        return error_response('Something went wrong', code=500)


@route.post('/register')
@roles('admin')
def register_new_member():
    json_data = request.get_json()

    try:
        register_data = RegisterRequest(**json_data)
        otp_token = register_member(register_data)
        return success_response({ 'otp': otp_token }, code=201)
    except ValidationError as e:
        logger.exception(f"Unexpected system crash. Details: {e}")
        return error_response('Request to register member is not valid')
    except HTTPException as e:
        return error_response(e.description or 'Something went wrong', code=e.code or 500)
    except Exception as e:
        logger.exception(f"Unexpected system crash. Details: {e}")
        return error_response('Something went wrong', code=500)

@route.post('/login')
def login():
    json_data = request.get_json()

    try:
        login_data = LoginRequest(**json_data)
        login_response = login_member(login_data)
        return success_response(login_response)
    except ValidationError as e:
        logger.exception(f"Unexpected system crash. Details: {e}")
        return error_response('Login request is not valid')
    except HTTPException as e:
        return error_response(e.description or 'Something went wrong', code=e.code or 500)
    except Exception as e:
        logger.exception(f"Unexpected system crash. Details: {e}")
        return error_response('Something went wrong', code=500)

@route.patch('/me')
def update_me():
    json_data = request.get_json()

    try:
        update_data = UpdateProfileRequest(**json_data)
        result = update_profile(g.user['user_id'], update_data)
        return success_response(result)
    except ValidationError as e:
        logger.exception(f"Unexpected system crash. Details: {e}")
        return error_response('Profile update request is not valid')
    except HTTPException as e:
        return error_response(e.description or 'Something went wrong', code=e.code or 500)
    except Exception as e:
        logger.exception(f"Unexpected system crash. Details: {e}")
        return error_response('Something went wrong', code=500)

@route.post('/change-password')
def change_password_route():
    json_data = request.get_json()

    try:
        change_password_data = ChangePasswordRequest(**json_data)
        change_password(g.user['user_id'], change_password_data)
        return success_response({})
    except ValidationError as e:
        logger.exception(f"Unexpected system crash. Details: {e}")
        return error_response('Change password request is not valid')
    except HTTPException as e:
        return error_response(e.description or 'Something went wrong', code=e.code or 500)
    except Exception as e:
        logger.exception(f"Unexpected system crash. Details: {e}")
        return error_response('Something went wrong', code=500)

@route.get('/verify')
def check_verification_token():
    token = request.args.get('token', '')

    try:
        result = check_otp_token(token)
        return success_response(result)
    except HTTPException as e:
        return error_response(e.description or 'Something went wrong', code=e.code or 500)
    except Exception as e:
        logger.exception(f"Unexpected system crash. Details: {e}")
        return error_response('Something went wrong', code=500)

@route.post('/verify')
def verify_user():

    json_data = request.get_json()

    try:
        verify_user_data = VerifiedRequest(**json_data)
        verify_response = verified_user(verify_user_data)
        return success_response(verify_response)
    except ValidationError as e:
        logger.exception(f"Unexpected system crash. Details: {e}")
        return error_response('Verification request is not valid')
    except HTTPException as e:
        return error_response(e.description or 'Something went wrong', code=e.code or 500)
    except Exception as e:
        logger.exception(f"Unexpected system crash. Details: {e}")
        return error_response('Something went wrong', code=500)

@route.patch('/role/<user_id>')
@roles('admin')
def change_user_role(user_id):
    json_data = request.get_json()

    try:
        change_role_data = ChangeRoleRequest(**json_data)
        result = change_member_role(g.user['user_id'], user_id, change_role_data)
        return success_response(result)
    except ValidationError as e:
        logger.exception(f"Unexpected system crash. Details: {e}")
        return error_response('Change role request is not valid')
    except HTTPException as e:
        return error_response(e.description or 'Something went wrong', code=e.code or 500)
    except Exception as e:
        logger.exception(f"Unexpected system crash. Details: {e}")
        return error_response('Something went wrong', code=500)

@route.delete('/<user_id>')
@roles('admin')
def delete_user(user_id):
    try:
        delete_member(g.user['user_id'], user_id)
        return success_response({})
    except HTTPException as e:
        return error_response(e.description or 'Something went wrong', code=e.code or 500)
    except Exception as e:
        logger.exception(f"Unexpected system crash. Details: {e}")
        return error_response('Something went wrong', code=500)