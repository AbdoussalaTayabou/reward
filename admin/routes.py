"""
Module Admin — étape 8.

Fonctions :
- Dashboard avec stats globales (users, points crédités, retraits, etc.)
- CRUD Sondages (+ questions), Vidéos, Tâches
- Validation manuelle des retraits (paid / failed → remboursement des points)
- Validation manuelle des tâches en attente (reason="task-pending")
- Liste utilisateurs + détail (solde, historique, completions, parrainages)

Sécurité :
- Décorateur @admin_required qui vérifie current_user.is_admin
- Toutes les routes sont sous /admin et nécessitent login
"""
from functools import wraps
from datetime import datetime, timedelta

from flask import (
    Blueprint, render_template, redirect, url_for, flash,
    request, abort
)
from flask_login import login_required, current_user
from sqlalchemy import func

from extensions import db
from models import (
    User, Survey, SurveyQuestion, Video, Task,
    Completion, PointTransaction, Referral, Withdrawal,
    credit_points,
)

admin_bp = Blueprint("admin", __name__, template_folder="../templates/admin")


# ------------------------------------------------------------------ #
# Décorateur
# ------------------------------------------------------------------ #
def admin_required(view):
    @wraps(view)
    @login_required
    def wrapper(*args, **kwargs):
        if not getattr(current_user, "is_admin", False):
            abort(403)
        return view(*args, **kwargs)
    return wrapper


# ------------------------------------------------------------------ #
# Dashboard
# ------------------------------------------------------------------ #
@admin_bp.route("/")
@admin_required
def dashboard():
    now = datetime.utcnow()
    last_7 = now - timedelta(days=7)

    stats = {
        "users_total": db.session.query(func.count(User.id)).scalar() or 0,
        "users_7d": db.session.query(func.count(User.id))
                              .filter(User.created_at >= last_7).scalar() or 0,
        "points_credited": db.session.query(func.coalesce(func.sum(PointTransaction.delta), 0))
                                     .filter(PointTransaction.delta > 0).scalar() or 0,
        "points_balance_total": db.session.query(func.coalesce(func.sum(User.points_balance), 0)).scalar() or 0,
        "completions_total": db.session.query(func.count(Completion.id)).scalar() or 0,
        "withdrawals_pending": Withdrawal.query.filter_by(status="pending").count(),
        "withdrawals_paid": Withdrawal.query.filter_by(status="paid").count(),
        "tasks_pending": PointTransaction.query.filter_by(reason="task-pending").count(),
        "surveys_active": Survey.query.filter_by(active=True).count(),
        "videos_active": Video.query.filter_by(active=True).count(),
        "tasks_active": Task.query.filter_by(active=True).count(),
        "referrals_total": db.session.query(func.count(Referral.id)).scalar() or 0,
    }
    return render_template("admin/dashboard.html", stats=stats)


# ------------------------------------------------------------------ #
# Utilisateurs
# ------------------------------------------------------------------ #
@admin_bp.route("/users")
@admin_required
def users_list():
    page = request.args.get("page", 1, type=int)
    q = (request.args.get("q") or "").strip()
    query = User.query
    if q:
        query = query.filter(User.email.ilike(f"%{q}%"))
    pagination = query.order_by(User.id.desc()).paginate(page=page, per_page=25, error_out=False)
    return render_template("admin/users_list.html", pagination=pagination, q=q)


@admin_bp.route("/users/<int:user_id>")
@admin_required
def user_detail(user_id):
    user = db.session.get(User, user_id) or abort(404)
    txs = (PointTransaction.query.filter_by(user_id=user.id)
           .order_by(PointTransaction.id.desc()).limit(100).all())
    completions = (Completion.query.filter_by(user_id=user.id)
                   .order_by(Completion.id.desc()).limit(100).all())
    referrals_made = Referral.query.filter_by(referrer_id=user.id).count()
    return render_template("admin/user_detail.html",
                           user=user, txs=txs, completions=completions,
                           referrals_made=referrals_made)


@admin_bp.route("/users/<int:user_id>/toggle-admin", methods=["POST"])
@admin_required
def toggle_admin(user_id):
    user = db.session.get(User, user_id) or abort(404)
    if user.id == current_user.id:
        flash("Tu ne peux pas modifier ton propre statut admin.", "danger")
    else:
        user.is_admin = not bool(user.is_admin)
        db.session.commit()
        flash(f"{user.email} → admin={user.is_admin}", "success")
    return redirect(url_for("admin.user_detail", user_id=user.id))


@admin_bp.route("/users/<int:user_id>/adjust", methods=["POST"])
@admin_required
def adjust_points(user_id):
    user = db.session.get(User, user_id) or abort(404)
    try:
        delta = int(request.form.get("delta", "0"))
    except ValueError:
        delta = 0
    reason = (request.form.get("reason") or "admin-adjust").strip()[:200]
    if delta == 0:
        flash("Delta nul.", "info")
    else:
        credit_points(user, delta, reason=reason, reference=f"admin:{current_user.id}")
        db.session.commit()
        flash(f"{'+' if delta>0 else ''}{delta} points pour {user.email}.", "success")
    return redirect(url_for("admin.user_detail", user_id=user.id))


# ------------------------------------------------------------------ #
# Sondages (+ questions)
# ------------------------------------------------------------------ #
@admin_bp.route("/surveys")
@admin_required
def surveys_list():
    surveys = Survey.query.order_by(Survey.id.desc()).all()
    return render_template("admin/surveys_list.html", surveys=surveys)


@admin_bp.route("/surveys/new", methods=["GET", "POST"])
@admin_bp.route("/surveys/<int:survey_id>/edit", methods=["GET", "POST"])
@admin_required
def survey_form(survey_id=None):
    survey = db.session.get(Survey, survey_id) if survey_id else None
    if survey_id and not survey:
        abort(404)

    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        description = (request.form.get("description") or "").strip()
        points = int(request.form.get("points_reward") or 0)
        active = bool(request.form.get("active"))
        if not title or points <= 0:
            flash("Titre obligatoire et points > 0.", "danger")
            return redirect(request.url)

        if not survey:
            survey = Survey(title=title)
            db.session.add(survey)
        survey.title = title
        survey.description = description
        survey.points_reward = points
        survey.active = active

        # Gestion des questions : ids alignés avec textes/options (champs répétés)
        q_ids = request.form.getlist("q_id")
        q_texts = request.form.getlist("q_text")
        q_options = request.form.getlist("q_options")
        existing = {q.id: q for q in (survey.questions or [])}
        keep_ids = set()
        for qid, text, opts in zip(q_ids, q_texts, q_options):
            text = (text or "").strip()
            opts = (opts or "").strip()
            if not text or not opts:
                continue
            if qid and qid.isdigit() and int(qid) in existing:
                q = existing[int(qid)]
                q.text = text
                q.options = opts
                keep_ids.add(q.id)
            else:
                q = SurveyQuestion(text=text, options=opts)
                survey.questions.append(q)
        # Supprimer celles qu'on ne garde pas
        for qid, q in list(existing.items()):
            if qid not in keep_ids:
                db.session.delete(q)

        db.session.commit()
        flash("Sondage enregistré.", "success")
        return redirect(url_for("admin.surveys_list"))

    return render_template("admin/survey_form.html", survey=survey)


@admin_bp.route("/surveys/<int:survey_id>/delete", methods=["POST"])
@admin_required
def survey_delete(survey_id):
    survey = db.session.get(Survey, survey_id) or abort(404)
    db.session.delete(survey)
    db.session.commit()
    flash("Sondage supprimé.", "success")
    return redirect(url_for("admin.surveys_list"))


# ------------------------------------------------------------------ #
# Vidéos
# ------------------------------------------------------------------ #
@admin_bp.route("/videos")
@admin_required
def videos_list():
    videos = Video.query.order_by(Video.id.desc()).all()
    return render_template("admin/videos_list.html", videos=videos)


@admin_bp.route("/videos/new", methods=["GET", "POST"])
@admin_bp.route("/videos/<int:video_id>/edit", methods=["GET", "POST"])
@admin_required
def video_form(video_id=None):
    video = db.session.get(Video, video_id) if video_id else None
    if video_id and not video:
        abort(404)
    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        url = (request.form.get("url") or "").strip()
        duration = int(request.form.get("duration_seconds") or 0)
        points = int(request.form.get("points_reward") or 0)
        active = bool(request.form.get("active"))
        if not title or not url or duration <= 0 or points <= 0:
            flash("Tous les champs sont obligatoires (durée et points > 0).", "danger")
            return redirect(request.url)
        if not video:
            video = Video(title=title, url=url)
            db.session.add(video)
        video.title = title
        video.url = url
        video.duration_seconds = duration
        video.points_reward = points
        video.active = active
        db.session.commit()
        flash("Vidéo enregistrée.", "success")
        return redirect(url_for("admin.videos_list"))
    return render_template("admin/video_form.html", video=video)


@admin_bp.route("/videos/<int:video_id>/delete", methods=["POST"])
@admin_required
def video_delete(video_id):
    video = db.session.get(Video, video_id) or abort(404)
    db.session.delete(video)
    db.session.commit()
    flash("Vidéo supprimée.", "success")
    return redirect(url_for("admin.videos_list"))


# ------------------------------------------------------------------ #
# Tâches
# ------------------------------------------------------------------ #
@admin_bp.route("/tasks")
@admin_required
def tasks_list():
    tasks = Task.query.order_by(Task.id.desc()).all()
    return render_template("admin/tasks_list.html", tasks=tasks)


@admin_bp.route("/tasks/new", methods=["GET", "POST"])
@admin_bp.route("/tasks/<int:task_id>/edit", methods=["GET", "POST"])
@admin_required
def task_form(task_id=None):
    task = db.session.get(Task, task_id) if task_id else None
    if task_id and not task:
        abort(404)
    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        description = (request.form.get("description") or "").strip()
        action_url = (request.form.get("action_url") or "").strip() or None
        points = int(request.form.get("points_reward") or 0)
        active = bool(request.form.get("active"))
        if not title or not description or points <= 0:
            flash("Titre, description et points > 0 obligatoires.", "danger")
            return redirect(request.url)
        if not task:
            task = Task(title=title, description=description)
            db.session.add(task)
        task.title = title
        task.description = description
        task.action_url = action_url
        task.points_reward = points
        task.active = active
        db.session.commit()
        flash("Tâche enregistrée.", "success")
        return redirect(url_for("admin.tasks_list"))
    return render_template("admin/task_form.html", task=task)


@admin_bp.route("/tasks/<int:task_id>/delete", methods=["POST"])
@admin_required
def task_delete(task_id):
    task = db.session.get(Task, task_id) or abort(404)
    db.session.delete(task)
    db.session.commit()
    flash("Tâche supprimée.", "success")
    return redirect(url_for("admin.tasks_list"))


# ------------------------------------------------------------------ #
# Validation manuelle des tâches (reason="task-pending")
# ------------------------------------------------------------------ #
@admin_bp.route("/tasks-pending")
@admin_required
def tasks_pending():
    pendings = (PointTransaction.query
                .filter_by(reason="task-pending")
                .order_by(PointTransaction.id.desc())
                .limit(200).all())
    rows = []
    for p in pendings:
        # reference = "task:<id>|proof:<txt>"
        task_id = None
        proof = ""
        if p.reference:
            try:
                left, right = p.reference.split("|", 1)
                task_id = int(left.split(":", 1)[1])
                proof = right.split(":", 1)[1]
            except Exception:
                pass
        task = db.session.get(Task, task_id) if task_id else None
        user = db.session.get(User, p.user_id)
        rows.append({"pt": p, "task": task, "user": user, "proof": proof})
    return render_template("admin/tasks_pending.html", rows=rows)


@admin_bp.route("/tasks-pending/<int:pt_id>/approve", methods=["POST"])
@admin_required
def task_pending_approve(pt_id):
    pt = db.session.get(PointTransaction, pt_id) or abort(404)
    if pt.reason != "task-pending":
        abort(400)
    # parse task id
    task_id = None
    if pt.reference and pt.reference.startswith("task:"):
        try:
            task_id = int(pt.reference.split("|", 1)[0].split(":", 1)[1])
        except Exception:
            pass
    task = db.session.get(Task, task_id) if task_id else None
    user = db.session.get(User, pt.user_id) or abort(404)
    if not task:
        flash("Tâche introuvable.", "danger")
        return redirect(url_for("admin.tasks_pending"))

    credit_points(user, task.points_reward,
                  reason="task-completed", reference=f"task:{task.id}")
    pt.reason = "task-approved"
    db.session.commit()
    flash(f"+{task.points_reward} pts crédités à {user.email}.", "success")
    return redirect(url_for("admin.tasks_pending"))


@admin_bp.route("/tasks-pending/<int:pt_id>/reject", methods=["POST"])
@admin_required
def task_pending_reject(pt_id):
    pt = db.session.get(PointTransaction, pt_id) or abort(404)
    if pt.reason != "task-pending":
        abort(400)
    task_id = None
    if pt.reference and pt.reference.startswith("task:"):
        try:
            task_id = int(pt.reference.split("|", 1)[0].split(":", 1)[1])
        except Exception:
            pass
    # Supprimer la Completion pour que l'utilisateur puisse re-soumettre si besoin
    if task_id:
        c = Completion.query.filter_by(
            user_id=pt.user_id, item_type="task", item_id=task_id
        ).first()
        if c:
            db.session.delete(c)
    pt.reason = "task-rejected"
    db.session.commit()
    flash("Soumission rejetée.", "info")
    return redirect(url_for("admin.tasks_pending"))


# ------------------------------------------------------------------ #
# Retraits
# ------------------------------------------------------------------ #
@admin_bp.route("/withdrawals")
@admin_required
def withdrawals_list():
    status = request.args.get("status", "pending")
    q = Withdrawal.query
    if status in {"pending", "paid", "failed"}:
        q = q.filter_by(status=status)
    items = q.order_by(Withdrawal.id.desc()).limit(200).all()
    users = {u.id: u for u in User.query.filter(
        User.id.in_([w.user_id for w in items])
    ).all()} if items else {}
    return render_template("admin/withdrawals_list.html",
                           items=items, status=status, users=users)


@admin_bp.route("/withdrawals/<int:w_id>/mark", methods=["POST"])
@admin_required
def withdrawal_mark(w_id):
    w = db.session.get(Withdrawal, w_id) or abort(404)
    action = request.form.get("action")
    batch = (request.form.get("paypal_batch_id") or "").strip() or None

    if w.status != "pending":
        flash("Ce retrait n'est plus en attente.", "info")
        return redirect(url_for("admin.withdrawals_list"))

    user = db.session.get(User, w.user_id)
    if action == "paid":
        w.status = "paid"
        w.paypal_batch_id = batch
        db.session.add(PointTransaction(
            user_id=w.user_id, delta=0,
            reason="withdrawal-paid", reference=f"withdrawal:{w.id}"
        ))
        flash(f"Retrait #{w.id} marqué payé.", "success")
    elif action == "failed":
        w.status = "failed"
        # Rembourser les points
        if user:
            credit_points(user, w.points_spent,
                          reason="withdrawal-refund",
                          reference=f"withdrawal:{w.id}")
        flash(f"Retrait #{w.id} rejeté, {w.points_spent} pts remboursés.", "info")
    else:
        flash("Action inconnue.", "danger")
        return redirect(url_for("admin.withdrawals_list"))

    db.session.commit()
    return redirect(url_for("admin.withdrawals_list", status=w.status))
