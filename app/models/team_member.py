from app.common.helpers import (gen_uuid, jakarta_now)
from app.extensions import db

class TeamMember(db.Model):
    __table_name__ = 'team_member'

    user_id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    user_email = db.Column(db.String(100), nullable=False)
    password = db.Column(db.String)
    user_first_name = db.Column(db.String(50))
    user_last_name = db.Column(db.String(50))
    user_role = db.Column(db.String(50))

    created_at = db.Column(db.DateTime(timezone=True), default=jakarta_now, index=True)
    updated_at = db.Column(db.DateTime(timezone=True), default=jakarta_now, onupdate=jakarta_now)

    verified_at = db.Column(db.DateTime(timezone=True))
    otp_token = db.Column(db.String())
    deactivated_at = db.Column(db.DateTime(timezone=True))
    
    def to_dict(self):
        return {
            'user_id': self.user_id,
            'user_email': self.user_email,
            'password': self.password,
            'user_first_name': self.user_first_name,
            'user_last_name': self.user_last_name,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'verified_at': self.verified_at,
            'otp_token': self.otp_token,
            'user_role': self.user_role,
            'deactivated_at': self.deactivated_at
        }