from typing import Literal

from pydantic import BaseModel, Field

from .diagnosis import PossibleIssue

ReliabilityLevel = Literal["题面推断", "候选自测支持", "学生反馈支持", "更强证据支持"]


class SelfTestCase(BaseModel):
    title: str = "自测用例"
    input_text: str = ""
    expected_output: str | None = None
    observation_goal: str = ""
    explanation: str = ""
    source: ReliabilityLevel = "题面推断"
    reminder: str = "这是 AI 建议的自测，不代表覆盖全部隐藏测试。"


class StudentHintResult(BaseModel):
    overall_assessment: str
    confidence: Literal["low", "medium", "high"]
    reliability_level: ReliabilityLevel = "题面推断"
    reliability_note: str = "当前仅基于题面、样例和学生代码推断，可能遗漏隐藏测试。"
    evidence_sources: list[str] = Field(default_factory=list, max_length=5)
    possible_issues: list[PossibleIssue] = Field(default_factory=list, max_length=3)
    self_test_cases: list[SelfTestCase] = Field(default_factory=list, max_length=3)
    knowledge_points: list[str] = Field(default_factory=list, max_length=5)
    error_patterns: list[str] = Field(default_factory=list, max_length=5)
    next_step_checks: list[str] = Field(default_factory=list)
    encouragement_or_strategy: str
