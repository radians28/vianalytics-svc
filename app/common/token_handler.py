import jwt
from flask import current_app

ALGORITHM = "HS256"

def encode(payload: dict):
    return jwt.encode(payload, current_app.config["JWT_SECRET_KEY"], algorithm=ALGORITHM)

def validate_token(token: str):
    return jwt.decode(token, current_app.config["JWT_SECRET_KEY"], algorithms=ALGORITHM)
