from flask import Blueprint, request
from pydantic import ValidationError

from app.blueprints.sku_master.requests.list_request import SkuMasterPaginationRequest
from app.blueprints.sku_master.service import get_history, get_platforms, get_skus, search_skus
from app.common.helpers import success_response, error_response


# Read-only master data: any signed-in user (checked in before_request)
route = Blueprint('sku_master', __name__)


@route.post('')
def get_sku_list():
    try:
        request_body = SkuMasterPaginationRequest(**(request.get_json(silent=True) or {}))
    except ValidationError:
        return error_response("Request to get SKU list is not valid", 400)

    results = get_skus(request_body)
    return success_response(results['records'], meta=results['meta'])


@route.get('/search')
def search_sku():
    try:
        limit = min(max(int(request.args.get('limit', 20)), 1), 50)
    except ValueError:
        return error_response("limit must be a number", 400)
    return success_response(search_skus(request.args.get('q', ''), limit))


@route.get('/<int:sku_id>/history')
def get_sku_history(sku_id: int):
    return success_response(get_history(sku_id))


@route.get('/<int:sku_id>/platforms')
def get_sku_platforms(sku_id: int):
    return success_response(get_platforms(sku_id))
