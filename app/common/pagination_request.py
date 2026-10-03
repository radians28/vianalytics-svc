from enum import Enum
from functools import lru_cache
from typing import Any, ClassVar, Optional, Type

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import inspect as sa_inspect

from app.models.team_member import TeamMember


class SortOrder(str, Enum):
    ASC = "asc"
    DESC = "desc"

class PaginationRequest(BaseModel):
    filter: Optional[dict[str, Any]] = None
    sort: Optional[dict[str, SortOrder]] = None
    page: int = Field(default=1, ge=1)
    size: int = Field(default=10, ge=1)

    _allowed_columns: ClassVar[set[str]] = set()

    @field_validator("filter", "sort")
    @classmethod
    def validate_column_names(cls, value: Optional[dict]) -> Optional[dict]:
        if value is None:
            return value
        invalid = set(value.keys()) - cls._allowed_columns
        if invalid:
            raise ValueError(f"Invalid column(s): {', '.join(invalid)}")
        return value

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size

@lru_cache(maxsize=None)
def pagination_request_for(model: Type[DeclarativeBase]) -> Type[PaginationRequest]:
    columns = {c.key for c in sa_inspect(model).columns}

    return type(
        f"{model.__name__}PaginationRequest",
        (PaginationRequest,),
        {"_allowed_columns": columns},
    )

UserPaginationRequest = pagination_request_for(TeamMember)