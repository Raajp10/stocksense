import os
import secrets
from pathlib import Path
import sqlite3
from flask import Flask, render_template
from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from .extensions import db, login, csrf, migrate


@event.listens_for(Engine, "connect")
def sqlite_constraints(connection, _):
    if isinstance(connection, sqlite3.Connection):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=15000")


def create_app(config=None):
    app = Flask(__name__, instance_relative_config=True)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    production = os.getenv("APP_ENV") == "production"
    secret = os.getenv("SECRET_KEY")
    if production and (not secret or len(secret) < 32 or secret.startswith("replace-")):
        raise RuntimeError("Production requires a random SECRET_KEY of at least 32 characters")
    if not secret:
        secret_path = Path(app.instance_path) / "session-secret"
        if not secret_path.exists():
            secret_path.write_text(secrets.token_hex(32))
            secret_path.chmod(0o600)
        secret = secret_path.read_text().strip()
    url = os.getenv("DATABASE_URL", "sqlite:///stocksense.db")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    app.config.update(SECRET_KEY=secret, SQLALCHEMY_DATABASE_URI=url,
        SQLALCHEMY_TRACK_MODIFICATIONS=False, MAX_CONTENT_LENGTH=12*1024*1024,
        UPLOAD_DIR=os.getenv("UPLOAD_DIR", str(Path(app.instance_path)/"uploads")),
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=production, WTF_CSRF_TIME_LIMIT=3600)
    if config:
        app.config.update(config)
    Path(app.config["UPLOAD_DIR"]).mkdir(parents=True, exist_ok=True)
    db.init_app(app)
    login.init_app(app)
    csrf.init_app(app)
    migrate.init_app(app, db, render_as_batch=True)
    login.login_view = "auth.login_view"
    from .models import User

    @login.user_loader
    def load_user(uid):
        user = db.session.get(User, int(uid))
        return user if user and user.active else None

    from .routes import auth, catalog, inventory, orders, dashboard, exports
    for blueprint in (auth, catalog, inventory, orders, dashboard, exports):
        app.register_blueprint(blueprint)
    from .documents import imports
    from .reviews import reviews
    app.register_blueprint(imports)
    app.register_blueprint(reviews)
    from .cli import register_commands
    register_commands(app)

    @app.get("/health")
    def health():
        db.session.execute(text("SELECT 1"))
        return {"status": "ok", "application": "StockSense"}

    @app.template_filter("money")
    def money(cents):
        return f"${cents // 100:,}.{cents % 100:02d}"

    from .services.common import DomainError

    @app.errorhandler(DomainError)
    def domain_error(error):
        from werkzeug.exceptions import BadRequest
        return render_template("error.html", error=BadRequest(str(error))), 400

    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(413)
    def error_page(error):
        return render_template("error.html", error=error), error.code

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "camera=(self), microphone=()"
        response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; media-src 'self' blob:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        if response.mimetype == "text/html":
            response.headers["Cache-Control"] = "no-store"
        return response
    return app
