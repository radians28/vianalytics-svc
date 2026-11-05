"""Models of the `royal_canin` data-warehouse schema (stg -> m -> t -> dm, plus log)."""
SCHEMA = 'royal_canin'

from app.models.royal_canin.log import LogEtlRun, LogEtlStep, LogDqIssue, LogSkuMatch  # noqa: E402
from app.models.royal_canin.staging import (  # noqa: E402
    StgShopee,
    StgTokopedia,
    StgTiktok,
    StgBlibli,
    StgLazada,
    StgSkuBundle,
    StgTraffic,
    StgUniqueSku,
)
from app.models.royal_canin.master import (  # noqa: E402
    MChannel,
    MCity,
    MSku,
    MSkuAlias,
    MPlatformSku,
    MSkuHistory,
    MSkuBundle,
)
from app.models.royal_canin.transaction import (  # noqa: E402
    TOrder,
    TOrderDetail,
    TOrderDetailDq,
    TTraffic,
)
from app.models.royal_canin.datamart import (  # noqa: E402
    DmSalesDaily,
    DmSalesSkuDaily,
)

__all__ = [
    'SCHEMA',
    'LogEtlRun',
    'LogEtlStep',
    'LogDqIssue',
    'LogSkuMatch',
    'StgShopee',
    'StgTokopedia',
    'StgTiktok',
    'StgBlibli',
    'StgLazada',
    'StgSkuBundle',
    'StgTraffic',
    'StgUniqueSku',
    'MChannel',
    'MCity',
    'MSku',
    'MSkuAlias',
    'MPlatformSku',
    'MSkuHistory',
    'MSkuBundle',
    'TOrder',
    'TOrderDetail',
    'TOrderDetailDq',
    'TTraffic',
    'DmSalesDaily',
    'DmSalesSkuDaily',
]
