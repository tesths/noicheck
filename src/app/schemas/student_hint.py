from typing import Literal

from pydantic import BaseModel, Field

from .diagnosis import PossibleIssue


class StudentHintResult(BaseModel):
    overall_assessment: str
    confidence: Literal["low", "medium", "high"]
    possible_issues: list[PossibleIssue] = Field(default_factory=list, max_length=3)
    next_step_checks: list[str] = Field(default_factory=list)
    encouragement_or_strategy: str
