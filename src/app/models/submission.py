import secrets
from datetime import datetime, timezone

from ..extensions import db


def _generate_public_id() -> str:
    return secrets.token_urlsafe(8)


class Submission(db.Model):
    __tablename__ = "submissions"

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(32), nullable=False, unique=True, index=True, default=_generate_public_id)
    student_name = db.Column(db.String(80), nullable=False)
    problem_url = db.Column(db.String(500), nullable=False)
    problem_source = db.Column(db.String(32), nullable=False, default="openjudge")
    problem_title = db.Column(db.String(255), nullable=True)
    problem_path = db.Column(db.String(120), nullable=True, index=True)
    language = db.Column(db.String(16), nullable=False, default="cpp")
    code_text = db.Column(db.Text, nullable=False)
    client_ip_hash = db.Column(db.String(64), nullable=True, index=True)
    fetch_status = db.Column(db.String(16), nullable=False, default="pending")
    diagnosis_status = db.Column(db.String(16), nullable=False, default="pending")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    problem_snapshot = db.relationship(
        "ProblemSnapshot",
        back_populates="submission",
        uselist=False,
        cascade="all, delete-orphan",
    )
    diagnosis_runs = db.relationship(
        "DiagnosisRun",
        back_populates="submission",
        cascade="all, delete-orphan",
    )

    @property
    def latest_diagnosis_run(self):
        if not self.diagnosis_runs:
            return None
        return max(self.diagnosis_runs, key=lambda item: item.created_at)
