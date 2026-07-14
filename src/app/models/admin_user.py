from datetime import datetime, timezone

from flask_login import UserMixin

from ..extensions import db


class AdminUser(UserMixin, db.Model):
    __tablename__ = "admin_users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    last_login_at = db.Column(db.DateTime(timezone=True), nullable=True)

    students = db.relationship("StudentUser", back_populates="owner_admin")

    def __repr__(self) -> str:
        return f"<AdminUser {self.username}>"
