from pydantic import BaseModel, Field, field_validator

from app.common.validators import validate_password_complexity

class VerifiedRequest(BaseModel):
    user_id: str = Field()
    otp_token: str = Field()
    password: str

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        return validate_password_complexity(value)