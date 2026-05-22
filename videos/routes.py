"""Module Vidéos avec anti-triche basique.

Principe anti-triche :
1. À l'ouverture de la page d'une vidéo, on émet un token signé (itsdangerous)
   contenant {user_id, video_id, issued_at}.
2. Le bouton "Réclamer mes points" n'est activé côté client qu'après la durée
   requise (compte à rebours JS).
3. Côté serveur, on vérifie :
   - signature du token (non falsifié)
   - user_id == current_user.id
   - video_id == celui réclamé
   - elapsed >= duration_seconds (le serveur recalcule, le client ne décide pas)
   - Completion unique (anti-doublon DB)
"""
from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, flash, abort, current_app, request
from flask_login import login_required, current_user
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from sqlalchemy.exc import IntegrityError

from extensions import db
from models import Video, Completion, credit_points

videos_bp = Blueprint("videos", __name__, template_folder="../templates")

TOKEN_SALT = "video-watch-v1"
# Le token expire après 1h max (durée raisonnable pour regarder une vidéo)
TOKEN_MAX_AGE = 3600


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=TOKEN_SALT)


def _completed_video_ids(user_id: int) -> set[int]:
    rows = Completion.query.filter_by(user_id=user_id, item_type="video").all()
    return {r.item_id for r in rows}


@videos_bp.route("/")
@login_required
def list_videos():
    videos = Video.query.filter_by(active=True).order_by(Video.id.desc()).all()
    done = _completed_video_ids(current_user.id)
    available = [v for v in videos if v.id not in done]
    completed = [v for v in videos if v.id in done]
    return render_template("videos/list.html", available=available, completed=completed)


@videos_bp.route("/<int:video_id>")
@login_required
def watch(video_id: int):
    video = Video.query.get_or_404(video_id)
    if not video.active:
        abort(404)

    # Déjà complétée ?
    already = Completion.query.filter_by(
        user_id=current_user.id, item_type="video", item_id=video.id
    ).first()
    if already:
        flash("Tu as déjà regardé cette vidéo.", "info")
        return redirect(url_for("videos.list_videos"))

    # Émet un token signé valable pour cette session de visionnage
    token = _serializer().dumps({"u": current_user.id, "v": video.id})
    return render_template("videos/watch.html", video=video, token=token)


@videos_bp.route("/<int:video_id>/claim", methods=["POST"])
@login_required
def claim(video_id: int):
    video = Video.query.get_or_404(video_id)
    token = request.form.get("token", "")

    # 1. Vérifie le token (signature + expiration)
    try:
        payload = _serializer().loads(token, max_age=TOKEN_MAX_AGE)
    except SignatureExpired:
        flash("Session expirée, relance la vidéo.", "error")
        return redirect(url_for("videos.watch", video_id=video.id))
    except BadSignature:
        flash("Token invalide.", "error")
        return redirect(url_for("videos.list_videos"))

    # 2. Vérifie que le token correspond au bon user/vidéo
    if payload.get("u") != current_user.id or payload.get("v") != video.id:
        flash("Token invalide.", "error")
        return redirect(url_for("videos.list_videos"))

    # 3. Recalcule le temps écoulé côté serveur (le client ne décide rien)
    # itsdangerous expose le timestamp via loads(..., return_timestamp=True)
    _, issued_at = _serializer().loads(token, max_age=TOKEN_MAX_AGE, return_timestamp=True)
    elapsed = (datetime.utcnow() - issued_at.replace(tzinfo=None)).total_seconds()
    if elapsed < video.duration_seconds:
        remaining = int(video.duration_seconds - elapsed)
        flash(f"Tu dois encore patienter {remaining}s avant de réclamer.", "error")
        return redirect(url_for("videos.watch", video_id=video.id))

    # 4. Anti-doublon DB (contrainte unique sur Completion)
    try:
        completion = Completion(
            user_id=current_user.id, item_type="video", item_id=video.id
        )
        db.session.add(completion)
        credit_points(
            user=current_user,
            amount=video.points_reward,
            reason=f"Vidéo : {video.title}",
        )
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("Vidéo déjà complétée.", "info")
        return redirect(url_for("videos.list_videos"))

    flash(f"+{video.points_reward} points crédités !", "success")
    return redirect(url_for("videos.list_videos"))
