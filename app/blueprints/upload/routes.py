import json
from flask import Blueprint, request, current_app

from app.blueprints.upload.service import upload, get_progress
from app.common.helpers import (
    success_response,
    error_response,
)

route = Blueprint('upload', __name__)

ALLOWED_EXTENSIONS = {"xlsx", "xls"}

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
    # TODO record the upload progress
    upload(metadata, file)
    return success_response({}, message="File uploaded successfully", code=201)

@route.post('/progress')
def progress_track():
    payload = request.get_json(silent=True) or {}

    results = get_progress(
        filter=payload.get('filter', {}),
        order=payload.get('order', {}),
        page=payload.get('page', 1),
        size=payload.get('size', 5)
        )

    return success_response(results['records'], meta=results['meta'])