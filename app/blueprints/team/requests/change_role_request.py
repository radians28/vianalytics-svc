from typing import Literal

from pydantic import BaseModel

class ChangeRoleRequest(BaseModel):
    user_role: Literal['admin', 'member']
