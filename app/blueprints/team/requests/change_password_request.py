from pydantic import BaseModel, field_validator

from app.common.validators import validate_password_complexity

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, value: str) -> str:
        return validate_password_complexity(value)
