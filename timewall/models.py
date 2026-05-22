from datetime import datetime
from extensions import db


class TimewallPostback(db.Model):
    """Journal de tous les postbacks reçus de TimeWall.
    `transaction_id` est UNIQUE pour garantir l'idempotence."""
    __tablename__ = "timewall_postbacks"

    id = db.Column(db.Integer, primary_key=True)
    transaction_id = db.Column(db.String(120), nullable=False, unique=True, index=True)
    user_ref = db.Column(db.String(64), nullable=False, index=True)  # userID envoyé par TW
    currency_amount = db.Column(db.Integer, nullable=False, default=0)
    revenue_usd = db.Column(db.Float, nullable=False, default=0.0)
    tw_type = db.Column(db.String(4), nullable=False, default="1")  # 1 credit, 2 chargeback
    offer_id = db.Column(db.String(64), nullable=True)
    offer_name = db.Column(db.String(255), nullable=True)
    ip = db.Column(db.String(64), nullable=True)
    status = db.Column(db.String(32), nullable=False, default="processing")
    raw_query = db.Column(db.Text, nullable=True)
    received_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    processed_at = db.Column(db.DateTime, nullable=True)
