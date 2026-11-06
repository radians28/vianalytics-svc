from typing import ClassVar

from pydantic import Field

from app.common.pagination_request import PaginationRequest


class SkuMasterPaginationRequest(PaginationRequest):
    """Filter/sort keys are the SKU master table's column keys in the UI."""
    size: int = Field(default=10, ge=1, le=100)

    _allowed_columns: ClassVar[set[str]] = {'skuId', 'sellerSku', 'productName'}
