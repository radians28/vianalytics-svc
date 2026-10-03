from functools import wraps
from flask import g, jsonify

def roles(*required_roles):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            # By the time a view runs, app.before_request's verify_access has
            # already validated the Bearer token and set g.user — no need for
            # a second, separate JWT check here.
            user = getattr(g, 'user', None)
            if user is None:
                return jsonify({"error": "Missing Authorization header"}), 401

            user_roles_in_token = set(user.get("roles", []))
            if not user_roles_in_token.intersection(required_roles):
                return jsonify({"error": "Forbidden: insufficient role"}), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator