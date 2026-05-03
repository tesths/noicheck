import json
import time
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from ..schemas import DiagnosisResult, StudentHintResult

PROMPT_VERSION = "v2"
STUDENT_PROMPT_VERSION = "student-v3"


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


@dataclass(slots=True)
class StudentHintResponse:
    result: StudentHintResult
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
        return self._diagnose(payload, audience="teacher")

    def diagnose_student(self, payload: DiagnosisPayload) -> StudentHintResponse:
        return self._diagnose(payload, audience="student")

    def _diagnose(
        self,
        payload: DiagnosisPayload,
        *,
        audience: str,
    ) -> DiagnosisResponse | StudentHintResponse:
        if not self.api_key:
            raise DiagnosisServiceError("未配置 AI API Key。")

        started_at = time.perf_counter()
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                temperature=0.2,
                response_format={"type": "json_object"},
                messages=self._build_messages(payload, audience=audience),
            )
        except Exception as exc:
            raise DiagnosisServiceError(f"调用 AI 服务失败：{exc}") from exc

        latency_ms = int((time.perf_counter() - started_at) * 1000)
        raw_content = response.choices[0].message.content or ""
        try:
            parsed = _parse_json_response(raw_content)
        except json.JSONDecodeError as exc:
            raise DiagnosisServiceError("模型返回的内容不是合法 JSON。") from exc

        if audience == "student":
            try:
                result = StudentHintResult.model_validate(_normalize_student_result_payload(parsed))
            except Exception as exc:
                raise DiagnosisServiceError("模型返回 JSON 结构不符合预期。") from exc
            return StudentHintResponse(
                result=result,
                raw_content=raw_content,
                latency_ms=latency_ms,
                model_name=self.model_name,
            )

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

    def _build_messages(self, payload: DiagnosisPayload, *, audience: str) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": self._build_system_prompt(audience)},
            {"role": "user", "content": self._build_user_prompt(payload, audience=audience)},
        ]

    def _build_system_prompt(self, audience: str) -> str:
        if audience == "student":
            return (
                "请根据题目和学生程序，帮学生找出程序可能错在哪里。"
                "不要提供正确答案、参考程序或完整可提交代码。"
                "不能直接给答案，一定要一步一步引导学生自己发现问题。"
                "不要假装运行过代码，只能根据题目和代码推断。"
                "除代码外，所有说明文字都必须使用简体中文。"
                "先用一句简短的话给出总体提示诊断，再展开后面的内容。"
                "解释原因时要尽量用小学生也能听懂的话，不要堆术语。"
                "要明确告诉学生下一步先做什么，步骤尽量小，一次只说一件事。"
                "语气要真诚、温和、鼓励，不能挖苦，也不要只说空话。"
                "如果学生提交的内容明显不是 C++ 程序，或和题目无关，不要继续分析代码逻辑。"
                "这种情况下要直接说明这里只能提交题目对应的程序代码，并提醒重新提交。"
                "诊断必须分成两部分："
                "第一部分是诊断原因，要指出可能出错的代码位置；"
                "第二部分是学生下一步提示，要给出可操作的检查方向、思路或鼓励，但不要直接写出正确答案。"
                "请输出严格 JSON，字段固定为 "
                "overall_assessment, confidence, possible_issues, next_step_checks, encouragement_or_strategy。"
                "possible_issues 最多 3 条，每条包含 title, location, evidence, explanation, suggested_fix。"
                "overall_assessment 必须先给总体提示诊断。"
                "possible_issues 的 explanation 和 suggested_fix 要尽量短、具体、易懂。"
                "next_step_checks 要按先后顺序告诉学生下一步做什么。"
                "encouragement_or_strategy 要给出真实鼓励。"
                "不要返回 correct_program，也不要在任何字段中写出完整参考程序。"
                + self._build_output_contract(audience)
            )
        return (
            "请根据题目和学生程序，帮老师检查程序可能错在哪里。"
            "不要假装运行过代码，只能根据题目和代码推断。"
            "除代码外，所有说明文字都必须使用简体中文。"
            "诊断必须分成两部分："
            "第一部分是诊断原因，要指出可能出错的代码位置；"
            "第二部分是完整正确程序。"
            "请输出严格 JSON，字段固定为 "
            "overall_assessment, confidence, missing_context, "
            "possible_issues, teacher_talking_points, next_step_checks, correct_program。"
            "possible_issues 最多 3 条，每条包含 title, location, evidence, explanation, suggested_fix。"
            "correct_program 必须给出一份可以直接参考的完整正确 C++ 程序。"
            + self._build_output_contract(audience)
        )

    def _build_user_prompt(self, payload: DiagnosisPayload, *, audience: str) -> str:
        if audience == "student":
            return "\n\n".join(
                [
                    "请你根据下面的题目和程序做学生版诊断。",
                    "输出重点只有两部分：",
                    "1. 诊断原因：指出程序可能错在哪里，并尽量说明可能出错的位置。",
                    "2. 学生下一步提示：给出可操作的检查方向、思路或鼓励，不要写出答案。",
                    "请先给一个总体提示诊断，再解释原因，再告诉学生下一步做什么，最后给鼓励。",
                    "解释时尽量用小学生也能听懂的话。",
                    "如果学生提交的内容明显不是 C++ 程序代码，请直接提醒这里只能提交题目对应的程序代码，不要继续分析算法。",
                    "除代码外，请所有说明都使用简体中文。",
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
        return "\n\n".join(
            [
                "请你根据下面的题目和程序做诊断。",
                "输出重点只有两部分：",
                "1. 诊断原因：指出程序可能错在哪里，并尽量说明可能出错的位置。",
                "2. 正确的完整程序：给出一份完整正确的 C++ 参考程序。",
                "除代码外，请所有说明都使用简体中文。",
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

    def _build_output_contract(self, audience: str) -> str:
        if audience == "student":
            return (
                "你必须只输出一个 JSON 对象。"
                "不要输出 Markdown 代码块，不要输出 ```json，不要输出任何前言、解释、结尾。"
                "第一个非空字符必须是 {，最后一个非空字符必须是 }。"
                '输出格式示例：{"overall_assessment":"...","confidence":"medium","possible_issues":[{"title":"...","location":"...","evidence":"...","explanation":"...","suggested_fix":"..."}],"next_step_checks":["..."],"encouragement_or_strategy":"..."}'
            )
        return (
            "你必须只输出一个 JSON 对象。"
            "不要输出 Markdown 代码块，不要输出 ```json，不要输出任何前言、解释、结尾。"
            "第一个非空字符必须是 {，最后一个非空字符必须是 }。"
            '输出格式示例：{"overall_assessment":"...","confidence":"medium","missing_context":[],"possible_issues":[{"title":"...","location":"...","evidence":"...","explanation":"...","suggested_fix":"..."}],"teacher_talking_points":["..."],"next_step_checks":["..."],"correct_program":"..."}'
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
    correct_program = (
        payload.get("correct_program")
        or payload.get("完整正确程序")
        or payload.get("正确程序")
        or payload.get("参考程序")
        or payload.get("完整程序")
        or ""
    )
    possible_issues = payload.get("possible_issues")
    if isinstance(possible_issues, list):
        normalized_issues = [_normalize_issue(item, overall, fix) for item in possible_issues][:3]
    else:
        normalized_issues = [
            {
                "title": str(title),
                "location": str(payload.get("location") or payload.get("错误位置") or "请重点检查核心逻辑所在的判断分支。"),
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
        "correct_program": str(correct_program),
    }


def _normalize_student_result_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TypeError("student diagnosis payload must be a JSON object")

    overall = (
        payload.get("overall_assessment")
        or payload.get("错误")
        or payload.get("结论")
        or payload.get("总结")
        or payload.get("analysis")
        or "程序存在需要检查的问题。"
    )
    hint = (
        payload.get("encouragement_or_strategy")
        or payload.get("鼓励建议")
        or payload.get("strategy")
        or "先从最可疑的一处开始检查。"
    )
    evidence = payload.get("证据") or payload.get("原因") or overall
    title = payload.get("title") or payload.get("问题标题") or "可能的主要问题"
    fallback_fix = str(hint)
    possible_issues = payload.get("possible_issues")
    if isinstance(possible_issues, list):
        normalized_issues = [_normalize_issue(item, overall, fallback_fix) for item in possible_issues][:3]
    else:
        normalized_issues = [
            {
                "title": str(title),
                "location": str(payload.get("location") or payload.get("错误位置") or "请重点检查核心逻辑所在的判断分支。"),
                "evidence": str(evidence),
                "explanation": str(overall),
                "suggested_fix": fallback_fix,
            }
        ]

    return {
        "overall_assessment": str(overall),
        "confidence": _normalize_confidence(payload.get("confidence")),
        "possible_issues": normalized_issues,
        "next_step_checks": _as_string_list(payload.get("next_step_checks")),
        "encouragement_or_strategy": str(hint),
    }


def _normalize_issue(item: Any, fallback_overall: str, fallback_fix: str) -> dict[str, str]:
    if not isinstance(item, dict):
        text = str(item)
        return {
            "title": "可能的问题",
            "location": "请重点检查相关逻辑块。",
            "evidence": text,
            "explanation": text,
            "suggested_fix": str(fallback_fix),
        }
    return {
        "title": str(item.get("title") or "可能的问题"),
        "location": str(item.get("location") or item.get("错误位置") or "请重点检查相关逻辑块。"),
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


def _parse_json_response(raw_content: str) -> Any:
    stripped = raw_content.strip()
    if not stripped:
        raise json.JSONDecodeError("empty content", raw_content, 0)

    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    candidate = _extract_first_json_object(stripped)
    return json.loads(candidate)


def _extract_first_json_object(text: str) -> str:
    start = text.find("{")
    if start == -1:
        raise json.JSONDecodeError("no json object found", text, 0)

    depth = 0
    in_string = False
    escaped = False

    for index in range(start, len(text)):
        char = text[index]

        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
            continue
        if char == "{":
            depth += 1
            continue
        if char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]

    raise json.JSONDecodeError("unterminated json object", text, start)
