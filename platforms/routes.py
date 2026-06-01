"""
Blueprint 'platforms' : hub centralisé pour toutes les sources de gains
(modules internes + plateformes externes) et endpoints de redirection /
postback génériques.

URL principales :
  GET  /earn                       -> hub
  GET  /earn/go/<slug>             -> redirige vers la plateforme externe
  GET  /earn/postback/<slug>       -> postback générique S2S
"""
import hashlib
import hmac
import os
from urllib.parse import urlencode

from flask import (
    Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
)
from flask_login import current_user, login_required

from extensions import db
from models import User
from models import credit_points

#from utils import credit_points  # helper existant (étape 1)
from platforms.registry import all_platforms, by_category, by_slug

platforms_bp = Blueprint("platforms", __name__, url_prefix="/earn")


# ---------------------------------------------------------------------------
# Hub
# ---------------------------------------------------------------------------
@platforms_bp.route("/")
def hub():
    message_id = request.args.get("message_id", "")
    if message_id:
        # CPX envoie des message_id comme :
        # success_complete, success_screenout, error_quality, etc.
        if message_id.startswith("success"):
            flash("Sondage terminé ! Tes points seront crédités sous peu.", "success")
        else:
            flash("Ce sondage ne correspondait pas à ton profil. Essaies-en un autre !", "info")

    return render_template(
        "earn/hub.html",
        categories=by_category(),
        platforms=all_platforms(),
    )


# ---------------------------------------------------------------------------
# Redirection vers une plateforme externe
# ---------------------------------------------------------------------------
@platforms_bp.route("/go/<slug>")
@login_required
def go(slug):
    p = by_slug(slug)
    if not p or not p["enabled"] or p.get("internal"):
        abort(404)

    # construit les variables (depuis env) à injecter dans l'URL
    ctx = {"user_id": current_user.id}
    for key, env_name in (p.get("config_env") or {}).items():
        val = os.environ.get(env_name, "")
        if not val:
            current_app.logger.warning(
                "Plateforme %s : variable %s non configurée", slug, env_name
            )
        ctx[key] = val

    if slug == "cpx-research":
        import hashlib
        from flask import url_for as _url_for
        app_id = ctx.get("app_id", "")
        user_id = str(current_user.id)
        cpx_secret = os.environ.get("CPX_RESEARCH_SECRET", "")
        secure_hash = hashlib.md5(f"{app_id}{user_id}{cpx_secret}".encode()).hexdigest()
        redirect_back = _url_for("platforms.hub", _external=True)
        url = (
            f"https://offers.cpx-research.com/index.php"
            f"?app_id={app_id}"
            f"&ext_user_id={user_id}"
            f"&secure_hash={secure_hash}"
            f"&subid_1=rewards"
            f"&output_method=redirect"
            f"&callback={redirect_back}?message_id={{message_id}}"
        )

    try:
        url = p["redirect_url"].format(**ctx)
    except KeyError as e:
        current_app.logger.error("Variable manquante pour %s : %s", slug, e)
        abort(500)

    return redirect(url, code=302)


# ---------------------------------------------------------------------------
# Postback S2S générique
#
# Convention d'URL :
#   /earn/postback/<slug>?user_id=...&amount=...&tx_id=...&sig=...
# La signature attendue est HMAC-SHA256(secret, f"{user_id}|{amount}|{tx_id}")
# ---------------------------------------------------------------------------
@platforms_bp.route("/postback/<slug>")
def postback(slug):
    p = by_slug(slug)
    if not p or p.get("internal"):
        abort(404)

    secret = os.environ.get(p.get("postback_secret_env", ""), "")
    if not secret:
        current_app.logger.error("Postback %s : secret manquant", slug)
        return "secret not configured", 500

    user_id = request.args.get("user_id", type=int)
    amount = request.args.get("amount", type=int)
    tx_id = request.args.get("tx_id", "")
    sig = request.args.get("sig", "")

    if not all([user_id, amount, tx_id, sig]):
        return "missing params", 400

    expected = hmac.new(
        secret.encode(),
        f"{user_id}|{amount}|{tx_id}".encode(),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, sig):
        current_app.logger.warning("Postback %s : signature invalide", slug)
        return "bad signature", 403

    user = User.query.get(user_id)
    if not user:
        return "user not found", 404

    # crédit idempotent via tx_id (helper existant doit gérer le doublon)
    credit_points(
        user=user,
        amount=amount,
        source=f"platform:{slug}",
        external_id=tx_id,
    )
    return "ok", 200
