"""
Module Tâches — petites missions à valider manuellement OU avec preuve (URL/texte).

Logique :
- L'utilisateur consulte la liste des tâches actives.
- Il ouvre une tâche, lit la consigne, clique sur action_url si fourni.
- Il soumet une "preuve" (URL d'une capture, pseudo, commentaire, etc.).
- On crée immédiatement un Completion (anti-doublon) + on crédite les points.
  → Si tu veux une VALIDATION MANUELLE, change `auto_validate` ci-dessous à False :
    on créera alors le Completion mais avec un statut "pending" via reason="task-pending"
    et les points ne seront crédités qu'après validation admin (à brancher plus tard).

Anti-fraude basique :
- 1 seule completion par (user, task) grâce à la contrainte unique sur Completion.
- Preuve obligatoire (min 5 caractères).
- Transaction atomique avec rollback sur IntegrityError.
"""
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError

from extensions import db
from models import Task, Completion, PointTransaction, credit_points

tasks_bp = Blueprint("tasks", __name__, template_folder="../templates/tasks")

AUTO_VALIDATE = True  # passe à False pour validation manuelle


@tasks_bp.route("/")
@login_required
def list_tasks():
    tasks = Task.query.filter_by(active=True).order_by(Task.id.desc()).all()
    done_ids = {
        c.item_id for c in Completion.query.filter_by(
            user_id=current_user.id, item_type="task"
        ).all()
    }
    available = [t for t in tasks if t.id not in done_ids]
    done = [t for t in tasks if t.id in done_ids]
    return render_template("tasks/list.html", available=available, done=done)


@tasks_bp.route("/<int:task_id>", methods=["GET", "POST"])
@login_required
def do_task(task_id: int):
    task = Task.query.filter_by(id=task_id, active=True).first_or_404()

    # Déjà fait ?
    already = Completion.query.filter_by(
        user_id=current_user.id, item_type="task", item_id=task.id
    ).first()
    if already:
        flash("Tu as déjà validé cette tâche.", "info")
        return redirect(url_for("tasks.list_tasks"))

    if request.method == "POST":
        proof = (request.form.get("proof") or "").strip()
        if len(proof) < 5:
            flash("Merci de fournir une preuve (URL, pseudo, commentaire — 5 caractères min).", "danger")
            return redirect(url_for("tasks.do_task", task_id=task.id))

        try:
            completion = Completion(
                user_id=current_user.id, item_type="task", item_id=task.id
            )
            db.session.add(completion)

            if AUTO_VALIDATE:
                credit_points(
                    current_user, task.points_reward,
                    reason="task-completed", reference=f"task:{task.id}"
                )
                db.session.commit()
                flash(f"+{task.points_reward} points ! Tâche validée.", "success")
            else:
                # Validation manuelle : on log la preuve dans une transaction "pending"
                db.session.add(PointTransaction(
                    user_id=current_user.id, delta=0,
                    reason="task-pending", reference=f"task:{task.id}|proof:{proof[:200]}"
                ))
                db.session.commit()
                flash("Soumission reçue. Un admin va vérifier ta preuve.", "info")

            return redirect(url_for("tasks.list_tasks"))

        except IntegrityError:
            db.session.rollback()
            flash("Tâche déjà validée.", "info")
            return redirect(url_for("tasks.list_tasks"))

    return render_template("tasks/do.html", task=task)
