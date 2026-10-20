from typing import ClassVar

from pydantic import Field

from app.common.pagination_request import PaginationRequest


class ProgressPaginationRequest(PaginationRequest):
    """Filter/sort keys are the upload table's column keys in the UI."""
    size: int = Field(default=5, ge=1, le=100)

    _allowed_columns: ClassVar[set[str]] = {'fileName', 'marketplace', 'status'}
