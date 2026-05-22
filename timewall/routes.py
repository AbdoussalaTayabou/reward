"""
Intégration TimeWall (offerwall).

Conformité aux exigences publisher TimeWall :
- iframe avec `userID` unique par utilisateur (notre User.id en string)
- endpoint S2S `/timewall/postback` accessible publiquement, en HTTPS en prod
- vérification de signature (hash configurable : sha256 par défaut, md5 supporté)
- idempotence stricte via `transactionID` (UNIQUE en base)
- gestion `type=1` (credit) et `type=2` (chargeback / reversal)
- IP whitelist optionnelle (TIMEWALL_ALLOWED_IPS)
- toujours répondre "1\\n" (TimeWall attend ce code) en cas de succès ;
  sinon une chaîne d'erreur explicite + status HTTP non-2xx pour déclencher
  le refire automatique de TimeWall
- journalisation complète (TimewallPostback) pour audit
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime
from ipaddress import ip_address, ip_network

from flask import Blueprint, abort, current_app, render_template, request
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError

from extensions import db
from models import User, credit_points
from .models import TimewallPostback

timewall_bp = Blueprint("timewall", __name__, template_folder="../templates")


# ---------- Helpers ----------

def _cfg(key: str, default: str = "") -> str:
    return current_app.config.get(key) or os.getenv(key, default)


def _hash(payload: str) -> str:
    algo = (_cfg("TIMEWALL_HASH_ALGO", "sha256") or "sha256").lower()
    if algo not in ("sha256", "md5", "sha1"):
        algo = "sha256"
    return hashlib.new(algo, payload.encode("utf-8")).hexdigest()


def _expected_signature(user_id: str, transaction_id: str, currency_amount: str) -> str:
    secret = _cfg("TIMEWALL_SECRET", "")
    # Format standard offerwall : userID + transactionID + currencyAmount + secret
    return _hash(f"{user_id}{transaction_id}{currency_amount}{secret}")


def _client_ip() -> str:
    fwd = request.headers.get("X-Forwarded-For", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.remote_addr or "0.0.0.0"


def _ip_allowed(ip: str) -> bool:
    raw = _cfg("TIMEWALL_ALLOWED_IPS", "").strip()
    if not raw:
        return True  # whitelist désactivée
    try:
        addr = ip_address(ip)
    except ValueError:
        return False
    for entry in (e.strip() for e in raw.split(",") if e.strip()):
        try:
            if "/" in entry:
                if addr in ip_network(entry, strict=False):
                    return True
            elif addr == ip_address(entry):
                return True
        except ValueError:
            continue
    return False


# ---------- Vue iframe (utilisateur connecté) ----------

@timewall_bp.route("/", endpoint="offerwall")
@login_required
def offerwall():
    app_key = _cfg("TIMEWALL_APP_KEY", "")
    # Format d'iframe officiel TimeWall : userID = identifiant unique côté publisher
    iframe_url = f"https://timewall.io/users/login?oid={app_key}&uid={current_user.id}"
    return render_template(
        "timewall/offerwall.html",
        iframe_url=iframe_url,
        configured=bool(app_key),
    )


# ---------- Endpoint S2S Postback ----------

@timewall_bp.route("/postback", methods=["GET"], endpoint="postback")
def postback():
    """
    TimeWall envoie un GET avec les paramètres :
      userID, transactionID, currencyAmount, revenue, type, hash
      (+ offerName, offerID, ip, country, etc. optionnels)

    Réponse attendue par TimeWall :
      "1" => OK (la transaction sera marquée comme livrée)
      autre / non-2xx => TimeWall réessaie automatiquement
    """
    ip = _client_ip()

    # 1) Whitelist IP
    if not _ip_allowed(ip):
        current_app.logger.warning("TimeWall postback IP refusée : %s", ip)
        return "FORBIDDEN_IP", 403

    # 2) Paramètres requis
    user_id_raw = request.args.get("userID") or request.args.get("userId") or request.args.get("user_id")
    transaction_id = request.args.get("transactionID") or request.args.get("transId") or request.args.get("transaction_id")
    currency_amount_raw = request.args.get("currencyAmount") or request.args.get("amount") or request.args.get("reward")
    revenue_raw = request.args.get("revenue") or request.args.get("payout") or "0"
    tw_type = (request.args.get("type") or "1").strip()  # "1" credit, "2" chargeback
    signature = request.args.get("hash") or request.args.get("signature") or ""
    offer_name = request.args.get("offerName") or request.args.get("offer_name") or ""
    offer_id = request.args.get("offerID") or request.args.get("offer_id") or ""

    if not (user_id_raw and transaction_id and currency_amount_raw is not None and signature):
        return "MISSING_PARAMS", 400

    # 3) Vérification de signature (constant-time)
    expected = _expected_signature(user_id_raw, transaction_id, str(currency_amount_raw))
    import hmac as _hmac
    if not _hmac.compare_digest(expected.lower(), signature.lower()):
        # On journalise quand même la tentative invalide
        db.session.add(TimewallPostback(
            transaction_id=transaction_id[:120], user_ref=str(user_id_raw)[:64],
            currency_amount=0, revenue_usd=0.0, tw_type=tw_type[:4],
            offer_id=str(offer_id)[:64], offer_name=str(offer_name)[:255],
            ip=ip[:64], status="bad_signature", raw_query=request.query_string.decode("utf-8", "ignore")[:2000],
        ))
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
        return "BAD_SIGNATURE", 401

    # 4) Parse numériques
    try:
        currency_amount = int(float(currency_amount_raw))
    except (TypeError, ValueError):
        return "BAD_AMOUNT", 400
    try:
        revenue_usd = float(revenue_raw or 0)
    except (TypeError, ValueError):
        revenue_usd = 0.0

    # 5) Utilisateur existant ?
    try:
        user = db.session.get(User, int(user_id_raw))
    except (TypeError, ValueError):
        user = None
    if user is None:
        db.session.add(TimewallPostback(
            transaction_id=transaction_id[:120], user_ref=str(user_id_raw)[:64],
            currency_amount=currency_amount, revenue_usd=revenue_usd, tw_type=tw_type[:4],
            offer_id=str(offer_id)[:64], offer_name=str(offer_name)[:255],
            ip=ip[:64], status="unknown_user", raw_query=request.query_string.decode("utf-8", "ignore")[:2000],
        ))
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
        return "UNKNOWN_USER", 404

    # 6) Idempotence : on tente d'insérer le postback en premier (UNIQUE sur transaction_id)
    log = TimewallPostback(
        transaction_id=transaction_id[:120],
        user_ref=str(user_id_raw)[:64],
        currency_amount=currency_amount,
        revenue_usd=revenue_usd,
        tw_type=tw_type[:4],
        offer_id=str(offer_id)[:64],
        offer_name=str(offer_name)[:255],
        ip=ip[:64],
        status="processing",
        raw_query=request.query_string.decode("utf-8", "ignore")[:2000],
    )
    db.session.add(log)
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        # Déjà traité => succès idempotent
        return "1", 200

    # 7) Crédit ou chargeback
    try:
        if tw_type == "2":
            # Chargeback / reversal : on retire les points (peut descendre en négatif si déjà retirés)
            credit_points(user, -abs(currency_amount),
                          reason="timewall-chargeback",
                          reference=f"tw:{transaction_id}")
            log.status = "chargeback"
        else:
            credit_points(user, abs(currency_amount),
                          reason="timewall-credit",
                          reference=f"tw:{transaction_id}")
            log.status = "credited"

        log.processed_at = datetime.utcnow()
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("TimeWall postback erreur de crédit : %s", exc)
        return "INTERNAL_ERROR", 500

    return "1", 200


# ---------- Endpoint de test (réservé à l'admin / dev) ----------

@timewall_bp.route("/_debug/signature", endpoint="debug_signature")
def debug_signature():
    """Outil interne : retourne la signature attendue pour un trio de params.
    Désactivé en prod sauf si DEBUG=True."""
    if not current_app.debug:
        abort(404)
    user_id = request.args.get("userID", "")
    transaction_id = request.args.get("transactionID", "")
    currency_amount = request.args.get("currencyAmount", "")
    return {
        "algo": (_cfg("TIMEWALL_HASH_ALGO", "sha256")).lower(),
        "payload_template": "userID + transactionID + currencyAmount + SECRET",
        "expected_hash": _expected_signature(user_id, transaction_id, currency_amount),
    }
