from typing import Literal

from pydantic import BaseModel, Field


class PossibleIssue(BaseModel):
    title: str
    location: str = Field(min_length=1)
    evidence: str
    explanation: str
    suggested_fix: str


class DiagnosisResult(BaseModel):
    overall_assessment: str
    confidence: Literal["low", "medium", "high"]
    missing_context: list[str] = Field(default_factory=list)
    possible_issues: list[PossibleIssue] = Field(default_factory=list, max_length=3)
    teacher_talking_points: list[str] = Field(default_factory=list)
    next_step_checks: list[str] = Field(default_factory=list)
    correct_program: str = Field(min_length=1)
