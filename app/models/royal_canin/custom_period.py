"""Custom reporting periods (P01-P13 per year), filled daily by the Airflow `custom_periods` DAG."""
from app.extensions import db
from app.models.royal_canin import SCHEMA


class CustomPeriod(db.Model):
    __tablename__ = 'custom_period'
    __table_args__ = {'schema': SCHEMA}

    period_key = db.Column(db.Integer, nullable=False, primary_key=True)
    year = db.Column(db.Integer, nullable=False)
    period = db.Column(db.String(3), nullable=False)
    period_start = db.Column(db.Date())
    period_end = db.Column(db.Date())

    def to_dict(self):
        return {
            'period_key': self.period_key,
            'year': self.year,
            'period': self.period,
            'period_start': self.period_start,
            'period_end': self.period_end
        }
