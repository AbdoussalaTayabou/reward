from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError

from extensions import db
from models import Survey, SurveyResponse, Completion, credit_points

surveys_bp = Blueprint("surveys", __name__, template_folder="../templates/surveys")


@surveys_bp.route("/")
@login_required
def list_surveys():
    # Sondages actifs non encore complétés par l'utilisateur
    done_ids = {
        c.item_id for c in current_user.completions.filter_by(item_type="survey").all()
    }
    surveys = Survey.query.filter_by(active=True).all()
    available = [s for s in surveys if s.id not in done_ids]
    done = [s for s in surveys if s.id in done_ids]
    return render_template("surveys/list.html", available=available, done=done)


@surveys_bp.route("/<int:survey_id>", methods=["GET", "POST"])
@login_required
def take_survey(survey_id: int):
    survey = Survey.query.get_or_404(survey_id)
    if not survey.active:
        abort(404)

    # Déjà complété ?
    already = Completion.query.filter_by(
        user_id=current_user.id, item_type="survey", item_id=survey.id
    ).first()
    if already:
        flash("Tu as déjà répondu à ce sondage.", "info")
        return redirect(url_for("surveys.list_surveys"))

    if request.method == "POST":
        # Toutes les questions doivent être répondues
        answers = {}
        for q in survey.questions:
            value = request.form.get(f"q_{q.id}", "").strip()
            if not value or value not in q.options_list():
                flash("Merci de répondre à toutes les questions.", "error")
                return render_template("surveys/take.html", survey=survey)
            answers[q.id] = value

        try:
            for qid, ans in answers.items():
                db.session.add(SurveyResponse(
                    user_id=current_user.id, question_id=qid, answer=ans
                ))
            db.session.add(Completion(
                user_id=current_user.id, item_type="survey", item_id=survey.id
            ))
            credit_points(
                current_user, survey.points_reward,
                reason=f"Sondage: {survey.title}",
                reference=f"survey:{survey.id}",
            )
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("Ce sondage a déjà été validé.", "info")
            return redirect(url_for("surveys.list_surveys"))

        flash(f"+{survey.points_reward} points ajoutés !", "success")
        return redirect(url_for("surveys.list_surveys"))

    return render_template("surveys/take.html", survey=survey)
