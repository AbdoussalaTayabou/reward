from flask import Blueprint, render_template, request, flash, redirect, url_for

pages_bp = Blueprint("pages", __name__, url_prefix="/p")


@pages_bp.route("/about")
def about():
    return render_template("pages/about.html")


@pages_bp.route("/how-it-works")
def how_it_works():
    return render_template("pages/how_it_works.html")


@pages_bp.route("/rewards")
def rewards():
    return render_template("pages/rewards.html")


@pages_bp.route("/faq")
def faq():
    return render_template("pages/faq.html")


@pages_bp.route("/contact", methods=["GET", "POST"])
def contact():
    if request.method == "POST":
        # Hook : envoyer un email / stocker en BDD plus tard.
        flash("Merci, votre message a bien été envoyé. Nous revenons vers vous sous 48 h.", "success")
        return redirect(url_for("pages.contact"))
    return render_template("pages/contact.html")


@pages_bp.route("/terms")
def terms():
    return render_template("pages/terms.html")


@pages_bp.route("/privacy")
def privacy():
    return render_template("pages/privacy.html")


@pages_bp.route("/legal")
def legal():
    return render_template("pages/legal.html")
