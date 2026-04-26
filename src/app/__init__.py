from pathlib import Path

from flask import Flask

from .bootstrap import bootstrap_app, validate_runtime_config
from .config import Config
from .extensions import csrf, db, login_manager, migrate
from .routes.admin import admin_bp
from .routes.public import public_bp
from .services.auth import register_auth_commands


def create_app(config_object: type[Config] | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_object or Config)
    validate_runtime_config(app)

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)

    app.register_blueprint(public_bp)
    app.register_blueprint(admin_bp)
    register_auth_commands(app)

    with app.app_context():
        bootstrap_app(app)

    return app
