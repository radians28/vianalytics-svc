from pydantic import BaseModel, Field

class UpdateProfileRequest(BaseModel):
    user_first_name: str = Field(..., min_length=1, max_length=50)
    user_last_name: str = Field(..., min_length=1, max_length=50)
