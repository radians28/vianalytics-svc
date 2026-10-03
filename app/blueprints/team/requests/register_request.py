from typing import Literal

from pydantic import BaseModel, EmailStr, Field

class RegisterRequest(BaseModel):
    user_email: EmailStr
    user_first_name: str = Field(..., min_length=0, max_length=50)
    user_last_name: str = Field(..., min_length=0, max_length=50)
    user_role: Literal['admin', 'member'] = 'member'