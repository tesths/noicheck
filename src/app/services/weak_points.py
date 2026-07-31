from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..models import StudentUser, Submission


@dataclass(frozen=True)
class WeakPointEvidence:
    public_id: str
    title: str
    created_at: datetime


@dataclass(frozen=True)
class WeakPointItem:
    label: str
    count: int
    evidence: list[WeakPointEvidence]

    @property
    def is_repeated(self) -> bool:
        return self.count >= 2


@dataclass(frozen=True)
class StudentWeakPointProfile:
    analyzed_submission_count: int
    knowledge_points: list[WeakPointItem]
    error_patterns: list[WeakPointItem]

    @property
    def has_evidence(self) -> bool:
        return bool(self.knowledge_points or self.error_patterns)

    @property
    def repeated_item_count(self) -> int:
        return sum(
            1
            for item in [*self.knowledge_points, *self.error_patterns]
            if item.is_repeated
        )


def build_student_weak_point_profile(
    student: StudentUser,
    *,
    item_limit: int = 5,
    evidence_limit: int = 3,
) -> StudentWeakPointProfile:
    submissions = sorted(
        (submission for submission in student.submissions if submission.deleted_at is None),
        key=lambda submission: submission.created_at,
        reverse=True,
    )
    analyzed_submission_count = 0
    knowledge_evidence: dict[str, list[WeakPointEvidence]] = {}
    error_evidence: dict[str, list[WeakPointEvidence]] = {}

    for submission in submissions:
        structured_result = _latest_student_structured_result(submission)
        if structured_result is None:
            continue

        knowledge_points = _normalized_labels(structured_result.get("knowledge_points"))
        error_patterns = _normalized_labels(structured_result.get("error_patterns"))
        if not knowledge_points and not error_patterns:
            continue

        analyzed_submission_count += 1
        evidence = WeakPointEvidence(
            public_id=submission.public_id,
            title=submission.problem_title or submission.problem_path or submission.problem_url,
            created_at=submission.created_at,
        )
        _add_submission_evidence(knowledge_evidence, knowledge_points, evidence)
        _add_submission_evidence(error_evidence, error_patterns, evidence)

    return StudentWeakPointProfile(
        analyzed_submission_count=analyzed_submission_count,
        knowledge_points=_rank_items(knowledge_evidence, item_limit=item_limit, evidence_limit=evidence_limit),
        error_patterns=_rank_items(error_evidence, item_limit=item_limit, evidence_limit=evidence_limit),
    )


def _latest_student_structured_result(submission: Submission) -> dict[str, Any] | None:
    student_runs = [
        run
        for run in submission.diagnosis_runs
        if run.audience == "student"
        and run.status == "success"
        and isinstance(run.structured_result_json, dict)
    ]
    if not student_runs:
        return None
    latest_success = max(student_runs, key=lambda run: run.created_at)
    return latest_success.structured_result_json


def _normalized_labels(raw_value: object) -> list[str]:
    if not isinstance(raw_value, list):
        return []

    labels: list[str] = []
    seen: set[str] = set()
    for item in raw_value:
        label = str(item).strip()
        if not label or label in {"-", "无", "暂无"} or label in seen:
            continue
        labels.append(label)
        seen.add(label)
    return labels


def _add_submission_evidence(
    target: dict[str, list[WeakPointEvidence]],
    labels: list[str],
    evidence: WeakPointEvidence,
) -> None:
    for label in labels:
        target.setdefault(label, []).append(evidence)


def _rank_items(
    evidence_by_label: dict[str, list[WeakPointEvidence]],
    *,
    item_limit: int,
    evidence_limit: int,
) -> list[WeakPointItem]:
    items = [
        WeakPointItem(
            label=label,
            count=len(evidence),
            evidence=evidence[:evidence_limit],
        )
        for label, evidence in evidence_by_label.items()
    ]
    return sorted(
        items,
        key=lambda item: (
            -item.count,
            -item.evidence[0].created_at.timestamp(),
            item.label,
        ),
    )[:item_limit]
