import os
from flask import Flask, render_template
from flask_login import current_user
from sqlalchemy import inspect, text
from dotenv import load_dotenv

 # ---- registry plateformes (Gagner) ----
from platforms.routes import platforms_bp
from platforms.registry import all_platforms

from extensions import db, login_manager
from models import User


def _ensure_schema():
    """Petite migration légère pour SQLite/Postgres : ajoute les colonnes
    manquantes qu'on a introduites après coup (ex: users.is_admin)."""
    insp = inspect(db.engine)
    if "users" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("users")}
        if "is_admin" not in cols:
            with db.engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE users ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT 0"
                ))


def create_app() -> Flask:
    load_dotenv()
    app = Flask(__name__)

    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///rewards.db")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    app.config["POINTS_PER_EUR"] = int(os.getenv("POINTS_PER_EUR", "1000"))
    app.config["MIN_WITHDRAW_EUR"] = float(os.getenv("MIN_WITHDRAW_EUR", "5"))
    app.config["REFERRAL_BONUS_POINTS"] = int(os.getenv("REFERRAL_BONUS_POINTS", "500"))

    db.init_app(app)
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id: str):
        return db.session.get(User, int(user_id))

    # Config TimeWall
    app.config["TIMEWALL_APP_KEY"] = os.getenv("TIMEWALL_APP_KEY", "")
    app.config["TIMEWALL_SECRET"] = os.getenv("TIMEWALL_SECRET", "")
    app.config["TIMEWALL_HASH_ALGO"] = os.getenv("TIMEWALL_HASH_ALGO", "sha256")
    app.config["TIMEWALL_ALLOWED_IPS"] = os.getenv("TIMEWALL_ALLOWED_IPS", "")

    from timewall.models import TimewallPostback  # noqa: F401

    # Blueprints
    from auth.routes import auth_bp
    from surveys.routes import surveys_bp
    from videos.routes import videos_bp
    from tasks.routes import tasks_bp
    from dashboard.routes import dashboard_bp
    from timewall.routes import timewall_bp
    from admin.routes import admin_bp
    from pages.routes import pages_bp  # NEW : pages marketing

    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(surveys_bp, url_prefix="/surveys")
    app.register_blueprint(videos_bp, url_prefix="/videos")
    app.register_blueprint(tasks_bp, url_prefix="/tasks")
    app.register_blueprint(dashboard_bp, url_prefix="/me")
    app.register_blueprint(timewall_bp, url_prefix="/timewall")
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(pages_bp)
    app.register_blueprint(platforms_bp)  # /p/about, /p/faq, ...

    @app.route("/")
    def index():
        return render_template("index.html", user=current_user)

    # Pages d'erreur soignées
    @app.errorhandler(404)
    def not_found(e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def server_error(e):
        return render_template("errors/500.html"), 500

    # ---------- CLI ----------
    @app.cli.command("seed-surveys")
    def seed_surveys():
        from models import Survey, SurveyQuestion
        if Survey.query.first():
            print("Sondages déjà présents.")
            return
        s = Survey(title="Tes habitudes en ligne",
                   description="Petit sondage rapide (3 questions).",
                   points_reward=50)
        s.questions = [
            SurveyQuestion(text="Combien d'heures passes-tu en ligne par jour ?",
                           options="0-2|2-5|5-8|8+"),
            SurveyQuestion(text="Quel réseau social utilises-tu le plus ?",
                           options="Instagram|TikTok|YouTube|X|Aucun"),
            SurveyQuestion(text="Préfères-tu les vidéos courtes ou longues ?",
                           options="Courtes|Longues|Les deux"),
        ]
        db.session.add(s)
        db.session.commit()
        print("Sondage de démo créé.")

    @app.cli.command("seed-videos")
    def seed_videos():
        from models import Video
        if Video.query.first():
            print("Vidéos déjà présentes.")
            return
        demos = [
            Video(title="Démo courte (YouTube)",
                  url="https://www.youtube.com/embed/dQw4w9WgXcQ",
                  duration_seconds=15, points_reward=20),
            Video(title="Démo Big Buck Bunny (mp4)",
                  url="https://download.blender.org/peach/bigbuckbunny_movies/BigBuckBunny_320x180.mp4",
                  duration_seconds=20, points_reward=30),
        ]
        db.session.add_all(demos)
        db.session.commit()
        print(f"{len(demos)} vidéos de démo créées.")

    @app.cli.command("seed-tasks")
    def seed_tasks():
        from models import Task
        if Task.query.first():
            print("Tâches déjà présentes.")
            return
        demos = [
            Task(title="Suivre notre compte Instagram",
                 description="1) Ouvre le lien.\n2) Clique sur « Suivre ».\n3) Reviens ici et colle ton pseudo Instagram comme preuve.",
                 action_url="https://instagram.com",
                 points_reward=30),
            Task(title="Tester une app mobile",
                 description="Installe l'app via le lien, ouvre-la une fois, puis colle une capture d'écran (URL imgur) comme preuve.",
                 action_url="https://example.com/app",
                 points_reward=100),
            Task(title="Donner ton avis (sans lien)",
                 description="Écris en 2-3 phrases ce que tu penses de cette plateforme. Ta réponse est la preuve.",
                 action_url=None,
                 points_reward=20),
        ]
        db.session.add_all(demos)
        db.session.commit()
        print(f"{len(demos)} tâches de démo créées.")

       

    @app.context_processor
    def inject_platforms():
        # disponible dans toutes les templates (base.html mega-menu)
        return {"nav_platforms": all_platforms()}

    @app.cli.command("create-admin")
    def create_admin():
        """Crée (ou promeut) un admin. Demande email + mot de passe en interactif."""
        import getpass
        email = input("Email admin : ").strip().lower()
        if not email:
            print("Email vide, abandon.")
            return
        user = User.query.filter_by(email=email).first()
        if user:
            user.is_admin = True
            db.session.commit()
            print(f"{email} promu admin.")
            return
        pwd = getpass.getpass("Mot de passe : ")
        if len(pwd) < 6:
            print("Mot de passe trop court.")
            return
        user = User(email=email, is_admin=True)
        user.set_password(pwd)
        db.session.add(user)
        db.session.commit()
        print(f"Admin créé : {email}")

    with app.app_context():
        db.create_all()
        _ensure_schema()

    return app


if __name__ == "__main__":
    create_app().run(debug=True)
