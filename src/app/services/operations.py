from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from ..models import DiagnosisRun, Submission

PROCESSING_STATUSES = {"queued", "running"}


@dataclass(frozen=True)
class OperationFailure:
    category: str
    submission_public_id: str
    student_label: str
    problem_title: str
    message: str
    created_at: datetime


@dataclass(frozen=True)
class OperationHealthSummary:
    total_submissions: int
    fetch_failed: int
    student_hint_failed: int
    teacher_diagnosis_failed: int
    fetch_processing: int
    student_hint_processing: int
    teacher_diagnosis_processing: int

    @property
    def total_failed(self) -> int:
        return self.fetch_failed + self.student_hint_failed + self.teacher_diagnosis_failed

    @property
    def total_processing(self) -> int:
        return (
            self.fetch_processing
            + self.student_hint_processing
            + self.teacher_diagnosis_processing
        )


@dataclass(frozen=True)
class OperationHealthReport:
    summary: OperationHealthSummary
    failures: list[OperationFailure]


def build_operation_health_report(
    submissions: Iterable[Submission],
    *,
    failure_limit: int = 20,
) -> OperationHealthReport:
    submission_list = list(submissions)
    failures: list[OperationFailure] = []

    fetch_failed = 0
    student_hint_failed = 0
    teacher_diagnosis_failed = 0
    fetch_processing = 0
    student_hint_processing = 0
    teacher_diagnosis_processing = 0

    for submission in submission_list:
        title = submission.problem_title or submission.problem_path or submission.problem_url

        if submission.fetch_status == "failed":
            fetch_failed += 1
            failures.append(
                OperationFailure(
                    category="抓题失败",
                    submission_public_id=submission.public_id,
                    student_label=submission.admin_student_label,
                    problem_title=title,
                    message=_fetch_failure_message(submission),
                    created_at=submission.created_at,
                )
            )
        elif submission.fetch_status in PROCESSING_STATUSES:
            fetch_processing += 1

        if submission.student_hint_status == "failed":
            student_hint_failed += 1
            failures.append(
                OperationFailure(
                    category="学生提示失败",
                    submission_public_id=submission.public_id,
                    student_label=submission.admin_student_label,
                    problem_title=title,
                    message=_diagnosis_failure_message(submission, audience="student"),
                    created_at=submission.created_at,
                )
            )
        elif submission.student_hint_status in PROCESSING_STATUSES:
            student_hint_processing += 1

        if submission.diagnosis_status == "failed":
            teacher_diagnosis_failed += 1
            failures.append(
                OperationFailure(
                    category="老师诊断失败",
                    submission_public_id=submission.public_id,
                    student_label=submission.admin_student_label,
                    problem_title=title,
                    message=_diagnosis_failure_message(submission, audience="teacher"),
                    created_at=submission.created_at,
                )
            )
        elif submission.diagnosis_status in PROCESSING_STATUSES:
            teacher_diagnosis_processing += 1

    failures = sorted(failures, key=lambda item: item.created_at, reverse=True)[:failure_limit]
    return OperationHealthReport(
        summary=OperationHealthSummary(
            total_submissions=len(submission_list),
            fetch_failed=fetch_failed,
            student_hint_failed=student_hint_failed,
            teacher_diagnosis_failed=teacher_diagnosis_failed,
            fetch_processing=fetch_processing,
            student_hint_processing=student_hint_processing,
            teacher_diagnosis_processing=teacher_diagnosis_processing,
        ),
        failures=failures,
    )


def _fetch_failure_message(submission: Submission) -> str:
    if submission.problem_snapshot and submission.problem_snapshot.fetch_error:
        return submission.problem_snapshot.fetch_error
    run = _latest_failed_run(submission, audience=None)
    if run and run.error_message:
        return run.error_message
    return "抓题任务失败，暂无详细原因。"


def _diagnosis_failure_message(submission: Submission, *, audience: str) -> str:
    run = _latest_failed_run(submission, audience=audience)
    if run and run.error_message:
        return run.error_message
    return "AI 任务失败，暂无详细原因。"


def _latest_failed_run(submission: Submission, *, audience: str | None) -> DiagnosisRun | None:
    runs = [
        run
        for run in submission.diagnosis_runs
        if run.status == "failed" and _run_matches_audience(run, audience=audience)
    ]
    if not runs:
        return None
    return max(runs, key=lambda run: run.created_at)


def _run_matches_audience(run: DiagnosisRun, *, audience: str | None) -> bool:
    if audience is None:
        return True
    if audience == "teacher":
        return (run.audience or "teacher") == "teacher"
    return run.audience == audience
