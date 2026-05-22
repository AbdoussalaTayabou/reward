from datetime import datetime
import secrets
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import db


def _gen_referral_code() -> str:
    return secrets.token_urlsafe(6)


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    points_balance = db.Column(db.Integer, default=0, nullable=False)

    referral_code = db.Column(db.String(16), unique=True, default=_gen_referral_code, nullable=False)
    referred_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    paypal_email = db.Column(db.String(255), nullable=True)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Relations
    transactions = db.relationship("PointTransaction", backref="user", lazy="dynamic")
    completions = db.relationship("Completion", backref="user", lazy="dynamic")
    withdrawals = db.relationship("Withdrawal", backref="user", lazy="dynamic")

    def set_password(self, raw: str) -> None:
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw: str) -> bool:
        return check_password_hash(self.password_hash, raw)


class Survey(db.Model):
    __tablename__ = "surveys"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    points_reward = db.Column(db.Integer, nullable=False, default=50)
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    questions = db.relationship("SurveyQuestion", backref="survey",
                                cascade="all, delete-orphan", lazy="joined")


class SurveyQuestion(db.Model):
    __tablename__ = "survey_questions"
    id = db.Column(db.Integer, primary_key=True)
    survey_id = db.Column(db.Integer, db.ForeignKey("surveys.id"), nullable=False)
    text = db.Column(db.String(500), nullable=False)
    # options séparées par "|" pour rester simple
    options = db.Column(db.String(1000), nullable=False)

    def options_list(self) -> list[str]:
        return [o for o in self.options.split("|") if o]


class SurveyResponse(db.Model):
    __tablename__ = "survey_responses"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey("survey_questions.id"), nullable=False)
    answer = db.Column(db.String(500), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Video(db.Model):
    __tablename__ = "videos"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    url = db.Column(db.String(500), nullable=False)  # URL embed (YouTube, mp4...)
    duration_seconds = db.Column(db.Integer, nullable=False, default=30)
    points_reward = db.Column(db.Integer, nullable=False, default=20)
    active = db.Column(db.Boolean, default=True, nullable=False)


class Task(db.Model):
    __tablename__ = "tasks"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=False)
    action_url = db.Column(db.String(500), nullable=True)
    points_reward = db.Column(db.Integer, nullable=False, default=30)
    active = db.Column(db.Boolean, default=True, nullable=False)


class Completion(db.Model):
    """Empêche un user de gagner plusieurs fois les points d'un même item."""
    __tablename__ = "completions"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    item_type = db.Column(db.String(20), nullable=False)  # 'survey' | 'video' | 'task'
    item_id = db.Column(db.Integer, nullable=False)
    completed_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("user_id", "item_type", "item_id", name="uniq_user_item"),
    )


class PointTransaction(db.Model):
    __tablename__ = "point_transactions"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    delta = db.Column(db.Integer, nullable=False)  # + ou -
    reason = db.Column(db.String(255), nullable=False)
    reference = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Referral(db.Model):
    __tablename__ = "referrals"
    id = db.Column(db.Integer, primary_key=True)
    referrer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    referee_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, unique=True)
    bonus_paid = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Withdrawal(db.Model):
    __tablename__ = "withdrawals"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    points_spent = db.Column(db.Integer, nullable=False)
    amount_eur = db.Column(db.Float, nullable=False)
    paypal_email = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(20), default="pending", nullable=False)  # pending|paid|failed
    paypal_batch_id = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# Helper
def credit_points(user: User, amount: int, reason: str, reference: str | None = None) -> None:
    user.points_balance = (user.points_balance or 0) + amount
    db.session.add(PointTransaction(
        user_id=user.id, delta=amount, reason=reason, reference=reference
    ))
