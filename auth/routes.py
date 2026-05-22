from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from extensions import db
from models import User, Referral
from .forms import SignupForm, LoginForm

auth_bp = Blueprint("auth", __name__, template_folder="../templates/auth")


@auth_bp.route("/signup", methods=["GET", "POST"])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    form = SignupForm()
    # Pré-remplir si ?ref=CODE dans l'URL
    if request.method == "GET" and request.args.get("ref"):
        form.referral.data = request.args.get("ref")

    if form.validate_on_submit():
        if User.query.filter_by(email=form.email.data.lower()).first():
            flash("Un compte existe déjà avec cet email.", "danger")
            return render_template("auth/signup.html", form=form)

        user = User(email=form.email.data.lower())
        user.set_password(form.password.data)

        # Parrainage
        ref_code = (form.referral.data or "").strip()
        if ref_code:
            referrer = User.query.filter_by(referral_code=ref_code).first()
            if referrer:
                user.referred_by_id = referrer.id

        db.session.add(user)
        db.session.flush()  # pour avoir user.id

        if user.referred_by_id:
            db.session.add(Referral(referrer_id=user.referred_by_id, referee_id=user.id))

        db.session.commit()
        login_user(user)
        flash("Bienvenue ! Ton compte est créé.", "success")
        return redirect(url_for("index"))

    return render_template("auth/signup.html", form=form)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower()).first()
        if user and user.check_password(form.password.data):
            login_user(user)
            return redirect(request.args.get("next") or url_for("index"))
        flash("Email ou mot de passe incorrect.", "danger")

    return render_template("auth/login.html", form=form)


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("index"))
