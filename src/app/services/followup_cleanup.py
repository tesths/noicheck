from dataclasses import dataclass

import click
from flask import Flask

from ..extensions import db
from ..models import SubmissionFollowupMessage
from .ai import normalize_student_followup_answer_text


@dataclass(slots=True)
class FollowupCleanupResult:
    scanned_count: int
    updated_count: int


def cleanup_legacy_followup_messages(*, dry_run: bool = False) -> FollowupCleanupResult:
    messages = (
        SubmissionFollowupMessage.query
        .filter_by(role="assistant")
        .order_by(SubmissionFollowupMessage.id.asc())
        .all()
    )

    updated_count = 0
    for message in messages:
        normalized_content = normalize_student_followup_answer_text(message.content)
        if not normalized_content or normalized_content == message.content:
            continue
        updated_count += 1
        if not dry_run:
            message.content = normalized_content

    if dry_run:
        db.session.rollback()
    else:
        db.session.commit()

    return FollowupCleanupResult(
        scanned_count=len(messages),
        updated_count=updated_count,
    )


def register_followup_cleanup_commands(app: Flask) -> None:
    @app.cli.command("clean-followup-history")
    @click.option("--dry-run", is_flag=True, help="只统计会更新多少条，不真正写回数据库。")
    def clean_followup_history(dry_run: bool) -> None:
        result = cleanup_legacy_followup_messages(dry_run=dry_run)
        action_text = "预计更新" if dry_run else "已更新"
        click.echo(
            f"{action_text} {result.updated_count} 条历史追问消息"
            f"（共检查 {result.scanned_count} 条 assistant 消息）。"
        )
