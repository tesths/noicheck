from datetime import datetime, timezone

from ..extensions import db


class DiagnosisRun(db.Model):
    __tablename__ = "diagnosis_runs"

    id = db.Column(db.Integer, primary_key=True)
    submission_id = db.Column(db.Integer, db.ForeignKey("submissions.id"), nullable=False, index=True)
    model_name = db.Column(db.String(100), nullable=False)
    prompt_version = db.Column(db.String(32), nullable=False, default="v1")
    status = db.Column(db.String(16), nullable=False, default="pending")
    structured_result_json = db.Column(db.JSON, nullable=True)
    summary_text = db.Column(db.Text, nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    latency_ms = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    submission = db.relationship("Submission", back_populates="diagnosis_runs")
