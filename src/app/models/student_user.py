from datetime import datetime, timezone

from ..extensions import db


class StudentUser(db.Model):
    __tablename__ = "student_users"

    id = db.Column(db.Integer, primary_key=True)
    nickname = db.Column(db.String(80), unique=True, nullable=False, index=True)
    real_name = db.Column(db.String(80), nullable=False, default="")
    password_hash = db.Column(db.String(255), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    last_login_at = db.Column(db.DateTime(timezone=True), nullable=True)

    submissions = db.relationship("Submission", back_populates="student_user")

    def __repr__(self) -> str:
        return f"<StudentUser {self.nickname}>"
