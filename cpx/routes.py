"""
Postback S2S dédié CPX Research.
Hash attendu : md5(f"{trans_id}-{app_secret}")
Status : 1 = complété, 2 = chargeback
IP whitelist : 188.40.3.73, 157.90.97.92
"""
import hashlib
import hmac
import os
from datetime import datetime

from flask import Blueprint, current_app, request
from sqlalchemy.exc import IntegrityError

from extensions import db
from models import User, credit_points
from timewall.models import TimewallPostback  # on réutilise le même modèle de log

cpx_bp = Blueprint("cpx", __name__, url_prefix="/cpx")

CPX_ALLOWED_IPS = {"188.40.3.73", "157.90.97.92"}


def _client_ip() -> str:
    fwd = request.headers.get("X-Forwarded-For", "")
    return fwd.split(",")[0].strip() if fwd else (request.remote_addr or "")


def _verify_hash(trans_id: str, secret: str, received_hash: str) -> bool:
    expected = hashlib.md5(f"{trans_id}-{secret}".encode()).hexdigest()
    return hmac.compare_digest(expected.lower(), received_hash.lower())


@cpx_bp.route("/postback")
def postback():
    ip = _client_ip()

    # 1. Whitelist IP (désactivée en debug)
    if not current_app.debug and ip not in CPX_ALLOWED_IPS:
        current_app.logger.warning("CPX postback IP refusée : %s", ip)
        return "FORBIDDEN_IP", 403

    # 2. Paramètres
    status       = request.args.get("status", "1")        # 1=complété, 2=chargeback
    trans_id     = request.args.get("trans_id", "")
    user_id_raw  = request.args.get("user_id", "")
    amount_local = request.args.get("amount_local", "0")  # points dans notre devise
    amount_usd   = request.args.get("amount_usd", "0")
    offer_id     = request.args.get("offer_id", "")
    received_hash = request.args.get("hash", "")

    if not (trans_id and user_id_raw and received_hash):
        return "MISSING_PARAMS", 400

    # 3. Vérification hash MD5
    secret = os.getenv("CPX_RESEARCH_SECRET", "")
    if not secret:
        current_app.logger.error("CPX_RESEARCH_SECRET non défini")
        return "SERVER_CONFIG_ERROR", 500

    if not _verify_hash(trans_id, secret, received_hash):
        current_app.logger.warning("CPX postback hash invalide : %s", trans_id)
        return "BAD_HASH", 401

    # 4. Parse montant
    try:
        points = int(float(amount_local))
    except (ValueError, TypeError):
        return "BAD_AMOUNT", 400

    # 5. Utilisateur
    try:
        user = db.session.get(User, int(user_id_raw))
    except (ValueError, TypeError):
        user = None
    if not user:
        return "UNKNOWN_USER", 404

    # 6. Idempotence via trans_id unique
    log = TimewallPostback(
        transaction_id=trans_id[:120],
        user_ref=str(user_id_raw)[:64],
        currency_amount=points,
        revenue_usd=float(amount_usd or 0),
        tw_type="2" if status == "2" else "1",
        offer_id=str(offer_id)[:64],
        offer_name="CPX Research",
        ip=ip[:64],
        status="processing",
        raw_query=request.query_string.decode("utf-8", "ignore")[:2000],
    )
    db.session.add(log)
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        return "1", 200  # déjà traité

    # 7. Crédit ou chargeback
    try:
        if status == "2":
            credit_points(user, -abs(points),
                          reason="cpx-chargeback",
                          reference=f"cpx:{trans_id}")
            log.status = "chargeback"
        else:
            credit_points(user, abs(points),
                          reason="cpx-survey",
                          reference=f"cpx:{trans_id}")
            log.status = "credited"

        log.processed_at = datetime.utcnow()
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("CPX postback erreur : %s", exc)
        return "INTERNAL_ERROR", 500

    return "1", 200