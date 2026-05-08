from datetime import datetime, timezone

from ..extensions import db


class SubmissionFollowupSession(db.Model):
    __tablename__ = "submission_followup_sessions"

    id = db.Column(db.Integer, primary_key=True)
    submission_id = db.Column(
        db.Integer,
        db.ForeignKey("submissions.id"),
        nullable=False,
        unique=True,
        index=True,
    )
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    submission = db.relationship("Submission", back_populates="followup_session")
    messages = db.relationship(
        "SubmissionFollowupMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="SubmissionFollowupMessage.id",
    )

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc)


class SubmissionFollowupMessage(db.Model):
    __tablename__ = "submission_followup_messages"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(
        db.Integer,
        db.ForeignKey("submission_followup_sessions.id"),
        nullable=False,
        index=True,
    )
    role = db.Column(db.String(16), nullable=False)
    content = db.Column(db.Text, nullable=False)
    context_label = db.Column(db.String(80), nullable=True)
    context_text = db.Column(db.Text, nullable=True)
    model_name = db.Column(db.String(100), nullable=True)
    latency_ms = db.Column(db.Integer, nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    session = db.relationship("SubmissionFollowupSession", back_populates="messages")

