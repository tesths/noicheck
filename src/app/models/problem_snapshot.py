from datetime import datetime, timezone

from ..extensions import db


class ProblemSnapshot(db.Model):
    __tablename__ = "problem_snapshots"

    id = db.Column(db.Integer, primary_key=True)
    submission_id = db.Column(db.Integer, db.ForeignKey("submissions.id"), nullable=False, unique=True)
    normalized_url = db.Column(db.String(500), nullable=False)
    title = db.Column(db.String(255), nullable=True)
    description_text = db.Column(db.Text, nullable=True)
    input_text = db.Column(db.Text, nullable=True)
    output_text = db.Column(db.Text, nullable=True)
    sample_input_text = db.Column(db.Text, nullable=True)
    sample_output_text = db.Column(db.Text, nullable=True)
    source_text = db.Column(db.Text, nullable=True)
    raw_excerpt = db.Column(db.Text, nullable=True)
    fetch_error = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    submission = db.relationship("Submission", back_populates="problem_snapshot")
