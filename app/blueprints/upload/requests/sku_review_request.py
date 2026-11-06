from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class SkuDecision(BaseModel):
    """What to do with one PENDING listing of log_sku_match."""
    matchId: int = Field(ge=1)
    action: Literal['map', 'create']
    # map: the SKU master (m_sku.sku_id) the listing belongs to
    skuId: Optional[int] = Field(default=None, ge=1)
    # create: product name of the new SKU; defaults to the listing's name
    productName: Optional[str] = Field(default=None, max_length=300)

    @model_validator(mode='after')
    def check_action(self):
        if self.action == 'map' and self.skuId is None:
            raise ValueError('map requires skuId')
        if self.action == 'create' and self.skuId is not None:
            raise ValueError('create does not take skuId')
        if self.productName is not None:
            self.productName = ' '.join(self.productName.split()) or None
        return self


class SkuReviewResolveRequest(BaseModel):
    decisions: list[SkuDecision] = Field(min_length=1, max_length=200)

    @field_validator('decisions')
    @classmethod
    def unique_matches(cls, value: list[SkuDecision]) -> list[SkuDecision]:
        ids = [d.matchId for d in value]
        if len(ids) != len(set(ids)):
            raise ValueError('each matchId may appear only once')
        return value
