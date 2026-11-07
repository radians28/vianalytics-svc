import json

from flask import Blueprint, g, request
from pydantic import ValidationError

from app.blueprints.sku_master.requests.list_request import SkuBundlePaginationRequest, SkuMasterPaginationRequest
from app.blueprints.sku_master.service import get_bundles, get_history, get_platforms, get_skus, search_skus
from app.blueprints.sku_master import bundle_upload, rebundle
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


@route.post('/bundles')
def get_bundle_list():
    try:
        request_body = SkuBundlePaginationRequest(**(request.get_json(silent=True) or {}))
    except ValidationError:
        return error_response("Request to get SKU bundles is not valid", 400)

    results = get_bundles(request_body)
    return success_response(results['records'], meta=results['meta'])


@route.post('/bundles/upload')
def upload_bundles():
    """SKU bundling file: mode 'preview' validates and reports, 'apply' replaces the bundles in the file."""
    file = request.files.get('file')
    if file is None or not file.filename:
        return error_response("No file selected", 400)
    if file.filename.rsplit('.', 1)[-1].lower() not in {'xlsx', 'xls', 'csv'}:
        return error_response("Unsupported file type. Allowed types: csv, xls, xlsx", 400)
    try:
        metadata = json.loads(request.form.get('data') or '{}')
    except json.JSONDecodeError:
        return error_response("Invalid JSON payload in 'data' field", 400)
    mode = (metadata.get('mode') if isinstance(metadata, dict) else None) or 'preview'
    if mode not in ('preview', 'apply'):
        return error_response("mode must be 'preview' or 'apply'", 400)

    data = file.read()
    try:
        if mode == 'preview':
            return success_response(bundle_upload.preview(data))
        user = g.user.get('user_email') or g.user.get('user_id')
        reconsolidate = bool(metadata.get('reconsolidate'))
        result = bundle_upload.apply(data, file.filename, user, reconsolidate=reconsolidate)
    except bundle_upload.BundleUploadError as err:
        return error_response(err.message, err.code, errors=err.errors or None)
    # stored order lines are re-split by Airflow, after the bundles are committed
    result['reconsolidate'] = (rebundle.start(result['changeIds'], user)
                               if reconsolidate and result['changeIds'] else None)
    return success_response(result, message=f"{result['bundles']} bundle(s) saved", code=201)


@route.get('/bundles/changes')
def bundle_changes():
    """Component list changes and their re-split state; ?status=PENDING,FAILED filters."""
    statuses = [s.strip().upper() for s in (request.args.get('status') or '').split(',') if s.strip()]
    return success_response(rebundle.list_changes(statuses))


@route.post('/bundles/reconsolidate')
def reconsolidate_bundles():
    """Re-split the stored order lines of open changes (body {changeIds?}; all open ones by default)."""
    body = request.get_json(silent=True) or {}
    ids = body.get('changeIds') or []
    if not isinstance(ids, list) or not all(isinstance(i, int) for i in ids):
        return error_response("changeIds must be a list of numbers", 400)
    result = rebundle.start(ids, g.user.get('user_email') or g.user.get('user_id'))
    if not result['changeIds']:
        return error_response(result['error'], 409)
    return success_response(result, message='Re-split started' if result['triggered'] else 'Re-split could not start')


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
