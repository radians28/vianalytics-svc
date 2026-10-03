from app.common.helpers import (gen_uuid, jakarta_now)
from app.extensions import db

class UploadProgress(db.Model):
    __table_name__ = 'upload_progress'

    upload_id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    file_name = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='Queued', index=True)
    total_rows = db.Column(db.Integer, nullable=True)
    processed_rows = db.Column(db.Integer, nullable=False, default=0)
    error_message = db.Column(db.Text, nullable=True)

    meta_data = db.Column(db.JSON, nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), default=jakarta_now, index=True)
    updated_at = db.Column(db.DateTime(timezone=True), default=jakarta_now, onupdate=jakarta_now)

    queued_at = db.Column(db.DateTime(timezone=True))
    processed_at = db.Column(db.DateTime(timezone=True))
    finished_at = db.Column(db.DateTime(timezone=True))
    last_heartbeat = db.Column(db.DateTime(timezone=True))

    def to_dict(self):
        return {
            'upload_id': self.upload_id,
            'file_name': self.file_name,
            'file_path': self.file_path,
            'status': self.status,
            'total_rows': self.total_rows,
            'processed_rows': self.processed_rows,
            'error_message': self.error_message,
            'meta_data': self.meta_data,
            'created_at': self.created_at,
            'updated_at': self.updated_at,

            'queued_at': self.queued_at,
            'processed_at': self.processed_at,
            'finished_at': self.finished_at
        }