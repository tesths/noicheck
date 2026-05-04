import hashlib
from datetime import datetime, timezone
from functools import wraps

import click
from flask import Flask, flash, g, redirect, session, url_for
from flask_login import login_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash

from ..extensions import db, login_manager
from ..models import AdminUser, StudentUser

STUDENT_SESSION_KEY = "student_user_id"
ACTIVE_ROLE_SESSION_KEY = "active_portal_role"
ADMIN_ROLE = "admin"
STUDENT_ROLE = "student"


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
    logout_student()
    login_user(admin, remember=remember)
    session[ACTIVE_ROLE_SESSION_KEY] = ADMIN_ROLE


def logout_admin() -> None:
    logout_user()
    if session.get(ACTIVE_ROLE_SESSION_KEY) == ADMIN_ROLE:
        session.pop(ACTIVE_ROLE_SESSION_KEY, None)


def authenticate_student(nickname: str, password: str) -> StudentUser | None:
    student = StudentUser.query.filter_by(nickname=nickname, is_active=True).first()
    if not student or not verify_password(student.password_hash, password):
        return None
    student.last_login_at = datetime.now(timezone.utc)
    return student


def login_student(student: StudentUser) -> None:
    logout_admin()
    session[STUDENT_SESSION_KEY] = student.id
    session[ACTIVE_ROLE_SESSION_KEY] = STUDENT_ROLE
    g.current_student = student


def logout_student() -> None:
    session.pop(STUDENT_SESSION_KEY, None)
    if session.get(ACTIVE_ROLE_SESSION_KEY) == STUDENT_ROLE:
        session.pop(ACTIVE_ROLE_SESSION_KEY, None)
    g.current_student = None


def enforce_exclusive_login() -> None:
    active_role = session.get(ACTIVE_ROLE_SESSION_KEY)
    has_student_session = session.get(STUDENT_SESSION_KEY) is not None
    has_admin_session = session.get("_user_id") is not None

    if active_role == ADMIN_ROLE:
        if has_student_session:
            session.pop(STUDENT_SESSION_KEY, None)
        g.current_student = None
        return

    if active_role == STUDENT_ROLE:
        if has_admin_session:
            logout_user()
        return

    if has_admin_session and has_student_session:
        session.pop(STUDENT_SESSION_KEY, None)
        g.current_student = None
        session[ACTIVE_ROLE_SESSION_KEY] = ADMIN_ROLE
    elif has_admin_session:
        session[ACTIVE_ROLE_SESSION_KEY] = ADMIN_ROLE
    elif has_student_session:
        session[ACTIVE_ROLE_SESSION_KEY] = STUDENT_ROLE


def current_student() -> StudentUser | None:
    cached = getattr(g, "current_student", None)
    if cached is not None:
        return cached

    student_id = session.get(STUDENT_SESSION_KEY)
    if not student_id:
        g.current_student = None
        return None

    student = db.session.get(StudentUser, int(student_id))
    if student is None or not student.is_active:
        session.pop(STUDENT_SESSION_KEY, None)
        g.current_student = None
        return None

    g.current_student = student
    return student


def student_login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if current_student() is None:
            flash("请先登录学生账号。", "error")
            return redirect(url_for("student.login"))
        return view(*args, **kwargs)

    return wrapped_view


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


def ensure_student_user(nickname: str, password: str, real_name: str = "") -> StudentUser:
    existing = StudentUser.query.filter_by(nickname=nickname).first()
    if existing:
        existing.real_name = real_name
        existing.password_hash = hash_password(password)
        existing.is_active = True
        return existing

    return StudentUser(nickname=nickname, real_name=real_name, password_hash=hash_password(password))


def register_auth_commands(app: Flask) -> None:
    @app.cli.command("init-admin")
    @click.option("--username", prompt=True)
    @click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
    def init_admin(username: str, password: str) -> None:
        admin = ensure_admin_user(username=username, password=password)
        db.session.add(admin)
        db.session.commit()
        click.echo(f"管理员 {username} 已初始化。")
