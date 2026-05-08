import secrets
from datetime import datetime, timezone

from ..extensions import db


def _generate_public_id() -> str:
    return secrets.token_urlsafe(8)


_STATUS_LABELS = {
    "pending": "待处理",
    "queued": "排队中",
    "running": "处理中",
    "success": "成功",
    "failed": "失败",
}

_SUBMISSION_MODE_LABELS = {
    "self_check": "自己提交",
    "teacher_review": "提交给老师",
}


def _status_label(value: str) -> str:
    return _STATUS_LABELS.get(value, value)


class Submission(db.Model):
    __tablename__ = "submissions"

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(32), nullable=False, unique=True, index=True, default=_generate_public_id)
    student_name = db.Column(db.String(80), nullable=False)
    student_user_id = db.Column(db.Integer, db.ForeignKey("student_users.id"), nullable=True, index=True)
    request_token = db.Column(db.String(64), nullable=True, unique=True, index=True)
    problem_url = db.Column(db.String(500), nullable=False)
    problem_source = db.Column(db.String(32), nullable=False, default="openjudge")
    problem_title = db.Column(db.String(255), nullable=True)
    problem_path = db.Column(db.String(120), nullable=True, index=True)
    language = db.Column(db.String(16), nullable=False, default="cpp")
    code_text = db.Column(db.Text, nullable=False)
    client_ip_hash = db.Column(db.String(64), nullable=True, index=True)
    submission_mode = db.Column(db.String(32), nullable=False, default="teacher_review")
    fetch_status = db.Column(db.String(16), nullable=False, default="pending")
    student_hint_status = db.Column(db.String(16), nullable=False, default="pending")
    diagnosis_status = db.Column(db.String(16), nullable=False, default="pending")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)
    student_user = db.relationship("StudentUser", back_populates="submissions")
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
    followup_session = db.relationship(
        "SubmissionFollowupSession",
        back_populates="submission",
        uselist=False,
        cascade="all, delete-orphan",
    )

    @property
    def latest_diagnosis_run(self):
        teacher_runs = [item for item in self.diagnosis_runs if (item.audience or "teacher") == "teacher"]
        if not teacher_runs:
            return None
        return max(teacher_runs, key=lambda item: item.created_at)

    @property
    def latest_student_hint_run(self):
        student_runs = [item for item in self.diagnosis_runs if item.audience == "student"]
        if not student_runs:
            return None
        return max(student_runs, key=lambda item: item.created_at)

    @property
    def fetch_status_label(self) -> str:
        return _status_label(self.fetch_status)

    @property
    def submission_mode_label(self) -> str:
        return _SUBMISSION_MODE_LABELS.get(self.submission_mode, self.submission_mode)

    @property
    def student_hint_status_label(self) -> str:
        return _status_label(self.student_hint_status)

    @property
    def diagnosis_status_label(self) -> str:
        return _status_label(self.diagnosis_status)

    @property
    def result_status(self) -> str:
        if self.submission_mode == "self_check":
            return self.student_hint_status
        return self.diagnosis_status

    @property
    def result_status_label(self) -> str:
        return _status_label(self.result_status)

    @property
    def admin_student_label(self) -> str:
        if self.student_user is None:
            return self.student_name
        return self.student_user.display_name

    @property
    def followup_messages(self):
        if self.followup_session is None:
            return []
        return self.followup_session.messages

    def mark_deleted(self) -> None:
        self.deleted_at = datetime.now(timezone.utc)
