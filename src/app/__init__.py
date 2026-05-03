from pathlib import Path

from flask import Flask, current_app, request

from .bootstrap import bootstrap_app, ensure_database_schema, validate_runtime_config
from .config import Config
from .extensions import csrf, db, login_manager, migrate
from .routes.admin import admin_bp
from .routes.internal import internal_bp
from .routes.public import public_bp
from .routes.student import student_bp
from .services.auth import register_auth_commands
from .services.auth import current_student
from .services.timezone import format_beijing_time


def create_app(config_object: type[Config] | None = None) -> Flask:
    public_dir = Path(__file__).resolve().parents[2] / "public"
    app = Flask(__name__, static_folder=str(public_dir), static_url_path="")
    app.config.from_object(config_object or Config)
    validate_runtime_config(app)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)

    app.register_blueprint(public_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(student_bp)
    app.register_blueprint(internal_bp)
    register_auth_commands(app)

    @app.context_processor
    def _inject_student_context() -> dict[str, object]:
        return {"current_student": current_student}

    @app.template_filter("beijing_datetime")
    def _format_beijing_datetime(value):
        return format_beijing_time(value)

    with app.app_context():
        bootstrap_app(app)

    @app.before_request
    def _ensure_database_schema_ready() -> None:
        if request.endpoint == "static":
            return
        ensure_database_schema(current_app)

    return app
