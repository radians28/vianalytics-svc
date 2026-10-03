from pydantic import BaseModel, EmailStr, field_validator

from app.common.validators import validate_password_complexity

class LoginRequest(BaseModel):
    user_email: EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        return validate_password_complexity(value)