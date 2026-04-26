import hashlib
from datetime import datetime, timezone

import click
from flask import Flask
from flask_login import login_user
from werkzeug.security import check_password_hash, generate_password_hash

from ..extensions import db, login_manager
from ..models import AdminUser


@login_manager.user_loader
def load_user(user_id: str) -> AdminUser | None:
    try:
        return db.session.get(AdminUser, int(user_id))
    except (TypeError, ValueError):
        return None


def hash_password(password: str) -> str:
    return generate_password_hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    return check_password_hash(password_hash, password)


def authenticate_admin(username: str, password: str) -> AdminUser | None:
    admin = AdminUser.query.filter_by(username=username, is_active=True).first()
    if not admin or not verify_password(admin.password_hash, password):
        return None
    admin.last_login_at = datetime.now(timezone.utc)
    return admin


def login_admin(admin: AdminUser, remember: bool = False) -> None:
    login_user(admin, remember=remember)


def hash_client_ip(ip_address: str | None) -> str | None:
    if not ip_address:
        return None
    return hashlib.sha256(ip_address.strip().encode("utf-8")).hexdigest()


def ensure_admin_user(username: str, password: str) -> AdminUser:
    existing = AdminUser.query.filter_by(username=username).first()
    if existing:
        existing.password_hash = hash_password(password)
        existing.is_active = True
        return existing

    return AdminUser(username=username, password_hash=hash_password(password))


def register_auth_commands(app: Flask) -> None:
    @app.cli.command("init-admin")
    @click.option("--username", prompt=True)
    @click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
    def init_admin(username: str, password: str) -> None:
        admin = ensure_admin_user(username=username, password=password)
        db.session.add(admin)
        db.session.commit()
        click.echo(f"管理员 {username} 已初始化。")
