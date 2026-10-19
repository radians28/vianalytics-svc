import json
from flask import Blueprint, request
from pydantic import ValidationError

from app.blueprints.upload.requests.progress_request import ProgressPaginationRequest
from app.blueprints.upload.service import UploadError, upload, get_progress
from app.common.helpers import (
    success_response,
    error_response,
)

route = Blueprint('upload', __name__)

ALLOWED_EXTENSIONS = {"xlsx", "xls", "csv"}

def _allowed(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@route.post('')
def upload_file():
    if 'file' not in request.files:
        return error_response("No file part in the request", 400)

    file = request.files['file']
    if file.filename is None or len(file.filename) < 1:
        return error_response("No file selected", 400)

    if not _allowed(filename=file.filename):
        return error_response(
            f"Unsupported file type. Allowed types: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
            400,
        )

    payload = request.form.get('data', '{}')
    try:
        metadata = json.loads(payload) if payload else {}
    except json.JSONDecodeError:
        return error_response("Invalid JSON payload in 'data' field", 400)
    if not isinstance(metadata, dict):
        return error_response("'data' field must be a JSON object", 400)

    try:
        result = upload(metadata, file)
    except UploadError as err:
        return error_response(err.message, err.code)
    return success_response(result, message="File uploaded successfully", code=201)

@route.post('/progress')
def progress_track():
    try:
        request_body = ProgressPaginationRequest(**(request.get_json(silent=True) or {}))
    except ValidationError:
        return error_response("Request to get upload progress is not valid", 400)

    results = get_progress(request_body)
    return success_response(results['records'], meta=results['meta'])
