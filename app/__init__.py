import jwt
import os
from datetime import datetime
from flask import Flask, jsonify, g, request
from flask.json.provider import DefaultJSONProvider
from flask_cors import CORS
from werkzeug.exceptions import HTTPException

from app.common.token_handler import validate_token
from app.common.helpers import to_jakarta
from app.config import Config
from app.extensions import db, migrate

class JakartaJSONProvider(DefaultJSONProvider):
    """Serialize datetimes as ISO 8601 in Jakarta time (e.g.
    2026-10-03T20:15:00+07:00) instead of Flask's default GMT HTTP-date."""

    @staticmethod
    def default(o):
        if isinstance(o, datetime):
            return to_jakarta(o).isoformat()
        return DefaultJSONProvider.default(o)


def create_app(config_class=Config):
    app = Flask(__name__)
    app.json = JakartaJSONProvider(app)

    app.config.from_object(config_class)

    if not app.config.get("JWT_SECRET_KEY"):
        raise RuntimeError("JWT_SECRET_KEY is not set; define it in the environment or .env")

    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    CORS(
        app,
        origins=app.config["CORS_ORIGINS"],
        supports_credentials=False,  # auth uses a Bearer token, not cookies
    )

    db.init_app(app)
    migrate.init_app(app, db)

    with app.app_context():
        from app import models

    from app.blueprints.upload.routes import route as upload_bp
    app.register_blueprint(upload_bp, url_prefix="/api/upload")

    from app.blueprints.team.routes import route as user_bp
    app.register_blueprint(user_bp, url_prefix="/api/user")

    @app.errorhandler(HTTPException)
    def handle_http_exception(err):
        response = {
            "success": False,
            "message": err.description,
            "code": err.code,
        }
        return jsonify(response), err.code

    @app.errorhandler(Exception)
    def handle_uncaught_exception(err):
        app.logger.exception(err)
        response = {
            "success": False,
            "message": "Internal server error",
            "code": 500,
        }
        return jsonify(response), 500

    public_paths = ['/api/user/login', '/api/user/verify']
    @app.before_request
    def verify_access():
        if request.method == "OPTIONS":
            # Let CORS preflight requests through unauthenticated.
            return None

        if request.path in public_paths:
            return None

        auth_header = request.headers.get("Authorization")
    
        if not auth_header:
            return jsonify({"error": "Missing Authorization header"}), 401
        
        try:
            # 3. Check for 'Bearer' prefix and split the string
            token_type, token = auth_header.split(" ")
            if token_type.lower() != "bearer":
                return jsonify({"error": "Authorization header must start with Bearer"}), 401
                
            payload = validate_token(token)
            
            g.user = payload

        except ValueError:
            return jsonify({"error": "Invalid Authorization header format"}), 401
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token has expired"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "Invalid token"}), 401

    return app