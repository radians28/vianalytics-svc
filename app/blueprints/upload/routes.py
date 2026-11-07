import json
from flask import Blueprint, g, request
from pydantic import ValidationError

from app.blueprints.upload.requests.progress_request import ProgressPaginationRequest
from app.blueprints.upload.requests.sku_review_request import SkuReviewResolveRequest
from app.blueprints.upload.service import UploadError, upload, get_progress
from app.blueprints.upload.sku_review import SkuReviewError, get_review, resolve, resume
from app.blueprints.upload.traffic import upload_traffic
from app.common.helpers import (
    success_response,
    error_response,
)

route = Blueprint('upload', __name__)

ALLOWED_EXTENSIONS = {"xlsx", "xls", "csv"}

def _allowed(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def read_upload_request():
    """(file, metadata) of a multipart upload: the `file` part and the JSON object in `data`.
    Returns an error response instead when the request is not valid."""
    if 'file' not in request.files:
        return None, error_response("No file part in the request", 400)

    file = request.files['file']
    if file.filename is None or len(file.filename) < 1:
        return None, error_response("No file selected", 400)

    if not _allowed(filename=file.filename):
        return None, error_response(
            f"Unsupported file type. Allowed types: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
            400,
        )

    payload = request.form.get('data', '{}')
    try:
        metadata = json.loads(payload) if payload else {}
    except json.JSONDecodeError:
        return None, error_response("Invalid JSON payload in 'data' field", 400)
    if not isinstance(metadata, dict):
        return None, error_response("'data' field must be a JSON object", 400)
    return (file, metadata), None


@route.post('')
def upload_file():
    parsed, error = read_upload_request()
    if error:
        return error
    file, metadata = parsed
    try:
        result = upload(metadata, file)
    except UploadError as err:
        return error_response(err.message, err.code)
    return success_response(result, message="File uploaded successfully", code=201)


@route.post('/traffic')
def upload_traffic_file():
    """A marketplace traffic export, loaded by svc straight into stg_traffic / t_traffic."""
    parsed, error = read_upload_request()
    if error:
        return error
    file, metadata = parsed
    try:
        result = upload_traffic(metadata, file, g.user.get('user_email') or g.user.get('user_id'))
    except UploadError as err:
        return error_response(err.message, err.code)
    return success_response(result, message=f"{result['days']} days of traffic loaded", code=201)

@route.post('/progress')
def progress_track():
    try:
        request_body = ProgressPaginationRequest(**(request.get_json(silent=True) or {}))
    except ValidationError:
        return error_response("Request to get upload progress is not valid", 400)

    results = get_progress(request_body)
    return success_response(results['records'], meta=results['meta'])


# SKU review of a Paused upload: any signed-in user can read, resolve and resume it

@route.get('/<upload_id>/sku-review')
def get_sku_review(upload_id: str):
    try:
        return success_response(get_review(upload_id))
    except SkuReviewError as err:
        return error_response(err.message, err.code)


@route.post('/<upload_id>/sku-review/resolve')
def resolve_sku_review(upload_id: str):
    try:
        request_body = SkuReviewResolveRequest(**(request.get_json(silent=True) or {}))
    except ValidationError as err:
        return error_response("Request to resolve SKUs is not valid", 400,
                              errors=[e['msg'] for e in err.errors()])
    try:
        result = resolve(upload_id, request_body, g.user.get('user_email') or g.user.get('user_id'))
    except SkuReviewError as err:
        return error_response(err.message, err.code)
    message = ('SKUs resolved; ETL resumed' if result['resume']['triggered']
               else 'SKUs resolved; ETL resume could not start')
    return success_response(result, message=message)


@route.post('/<upload_id>/resume')
def resume_upload(upload_id: str):
    try:
        result = resume(upload_id, g.user.get('user_email') or g.user.get('user_id'))
    except SkuReviewError as err:
        return error_response(err.message, err.code)
    message = 'ETL resumed' if result['resume']['triggered'] else 'ETL resume could not start'
    return success_response(result, message=message)
