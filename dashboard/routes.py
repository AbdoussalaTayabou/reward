"""
Module Dashboard — espace personnel de l'utilisateur.

Pages :
- /              → vue d'ensemble : solde, équivalent EUR, lien de parrainage,
                    nb d'items complétés par type, dernières transactions.
- /history       → historique complet des PointTransaction (paginé simple).
- /profile       → modifier son email PayPal (utilisé pour les retraits).

Dépend de :
- current_app.config["POINTS_PER_EUR"] et ["MIN_WITHDRAW_EUR"] définis dans app.py
- Modèles : PointTransaction, Completion, Referral
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from sqlalchemy import func

from extensions import db
from models import PointTransaction, Completion, Referral

dashboard_bp = Blueprint("dashboard", __name__, template_folder="../templates/dashboard")


def _points_to_eur(points: int) -> float:
    return round(points / current_app.config["POINTS_PER_EUR"], 2)


@dashboard_bp.route("/")
@login_required
def home():
    # Compteurs par type d'activité
    counts = dict(
        db.session.query(Completion.item_type, func.count(Completion.id))
        .filter(Completion.user_id == current_user.id)
        .group_by(Completion.item_type).all()
    )
    # Parrainages
    nb_filleuls = Referral.query.filter_by(referrer_id=current_user.id).count()

    # 10 dernières transactions
    last_tx = (PointTransaction.query
               .filter_by(user_id=current_user.id)
               .order_by(PointTransaction.created_at.desc())
               .limit(10).all())

    balance = current_user.points_balance or 0
    eur = _points_to_eur(balance)
    min_eur = current_app.config["MIN_WITHDRAW_EUR"]
    can_withdraw = eur >= min_eur

    # Lien de parrainage
    referral_url = url_for("auth.signup", ref=current_user.referral_code, _external=True)

    return render_template(
        "dashboard/home.html",
        balance=balance, eur=eur, min_eur=min_eur, can_withdraw=can_withdraw,
        counts=counts, nb_filleuls=nb_filleuls,
        last_tx=last_tx, referral_url=referral_url,
    )


@dashboard_bp.route("/history")
@login_required
def history():
    page = max(int(request.args.get("page", 1)), 1)
    per_page = 25
    q = (PointTransaction.query
         .filter_by(user_id=current_user.id)
         .order_by(PointTransaction.created_at.desc()))
    total = q.count()
    txs = q.offset((page - 1) * per_page).limit(per_page).all()
    has_next = page * per_page < total
    return render_template("dashboard/history.html",
                           txs=txs, page=page, has_next=has_next, total=total)


@dashboard_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "POST":
        email = (request.form.get("paypal_email") or "").strip()
        if email and "@" not in email:
            flash("Email PayPal invalide.", "danger")
            return redirect(url_for("dashboard.profile"))
        current_user.paypal_email = email or None
        db.session.commit()
        flash("Profil mis à jour.", "success")
        return redirect(url_for("dashboard.profile"))
    return render_template("dashboard/profile.html")
