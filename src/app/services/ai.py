import json
import time
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from ..schemas import DiagnosisResult

PROMPT_VERSION = "v1"


class DiagnosisServiceError(Exception):
    pass


@dataclass(slots=True)
class DiagnosisPayload:
    student_name: str
    problem_url: str
    problem_title: str | None
    description_text: str | None
    input_text: str | None
    output_text: str | None
    sample_input_text: str | None
    sample_output_text: str | None
    code_text: str


@dataclass(slots=True)
class DiagnosisResponse:
    result: DiagnosisResult
    raw_content: str
    latency_ms: int
    model_name: str


class DeepSeekDiagnosisService:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model_name: str,
        client: OpenAI | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self.client = client or OpenAI(api_key=api_key, base_url=self.base_url)

    def diagnose(self, payload: DiagnosisPayload) -> DiagnosisResponse:
        if not self.api_key:
            raise DiagnosisServiceError("未配置 DeepSeek API Key。")

        started_at = time.perf_counter()
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                temperature=0.2,
                response_format={"type": "json_object"},
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "请根据题目和学生程序，帮老师检查程序可能错在哪里。"
                            "不要假装运行过代码，只能根据题目和代码推断。"
                            "请输出严格 JSON，字段固定为 "
                            "overall_assessment, confidence, missing_context, "
                            "possible_issues, teacher_talking_points, next_step_checks。"
                            "possible_issues 最多 3 条，每条包含 title, evidence, explanation, suggested_fix。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": self._build_user_prompt(payload),
                    },
                ],
            )
        except Exception as exc:
            raise DiagnosisServiceError(f"调用 DeepSeek 失败：{exc}") from exc

        latency_ms = int((time.perf_counter() - started_at) * 1000)
        raw_content = response.choices[0].message.content or ""
        try:
            parsed = json.loads(raw_content)
        except json.JSONDecodeError as exc:
            raise DiagnosisServiceError("模型返回的内容不是合法 JSON。") from exc

        try:
            result = DiagnosisResult.model_validate(_normalize_result_payload(parsed))
        except Exception as exc:
            raise DiagnosisServiceError("模型返回 JSON 结构不符合预期。") from exc

        return DiagnosisResponse(
            result=result,
            raw_content=raw_content,
            latency_ms=latency_ms,
            model_name=self.model_name,
        )

    def _build_user_prompt(self, payload: DiagnosisPayload) -> str:
        return "\n\n".join(
            [
                "请你根据下面的题目和程序，检查程序可能错误的地方，并给出老师可直接转述的修改建议。",
                f"题目链接：{payload.problem_url}",
                f"题目标题：{payload.problem_title or '未知'}",
                f"题目描述：{payload.description_text or '未抓取到'}",
                f"输入格式：{payload.input_text or '未抓取到'}",
                f"输出格式：{payload.output_text or '未抓取到'}",
                f"样例输入：{payload.sample_input_text or '未抓取到'}",
                f"样例输出：{payload.sample_output_text or '未抓取到'}",
                f"学生：{payload.student_name}",
                "程序语言：C++",
                "程序：",
                payload.code_text,
            ]
        )


def _normalize_result_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TypeError("diagnosis payload must be a JSON object")

    overall = (
        payload.get("overall_assessment")
        or payload.get("错误")
        or payload.get("结论")
        or payload.get("总结")
        or payload.get("analysis")
        or "程序存在需要检查的问题。"
    )
    fix = (
        payload.get("修改建议")
        or payload.get("建议")
        or payload.get("recommended_fix")
        or payload.get("fix")
        or "请根据题目要求重新检查代码逻辑。"
    )
    evidence = payload.get("证据") or payload.get("原因") or overall
    title = payload.get("title") or payload.get("问题标题") or "可能的主要问题"
    possible_issues = payload.get("possible_issues")
    if isinstance(possible_issues, list):
        normalized_issues = [_normalize_issue(item, overall, fix) for item in possible_issues][:3]
    else:
        normalized_issues = [
            {
                "title": str(title),
                "evidence": str(evidence),
                "explanation": str(overall),
                "suggested_fix": str(fix),
            }
        ]

    return {
        "overall_assessment": str(overall),
        "confidence": _normalize_confidence(payload.get("confidence")),
        "missing_context": _as_string_list(payload.get("missing_context")),
        "possible_issues": normalized_issues,
        "teacher_talking_points": _as_string_list(payload.get("teacher_talking_points")) or [str(fix)],
        "next_step_checks": _as_string_list(payload.get("next_step_checks")),
    }


def _normalize_issue(item: Any, fallback_overall: str, fallback_fix: str) -> dict[str, str]:
    if not isinstance(item, dict):
        text = str(item)
        return {
            "title": "可能的问题",
            "evidence": text,
            "explanation": text,
            "suggested_fix": str(fallback_fix),
        }
    return {
        "title": str(item.get("title") or "可能的问题"),
        "evidence": str(item.get("evidence") or fallback_overall),
        "explanation": str(item.get("explanation") or fallback_overall),
        "suggested_fix": str(item.get("suggested_fix") or fallback_fix),
    }


def _as_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item) for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _normalize_confidence(value: Any) -> str:
    text = str(value).strip().lower() if value is not None else ""
    if text in {"low", "medium", "high"}:
        return text
    return "medium"
