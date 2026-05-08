import re
from dataclasses import dataclass

from flask import current_app

from ..extensions import db
from ..models import Submission, SubmissionFollowupMessage, SubmissionFollowupSession
from .ai import (
    DeepSeekDiagnosisService,
    DiagnosisServiceError,
    StudentFollowupPayload,
    StudentFollowupResponse,
)
from .settings import get_active_ai_model, get_student_system_prompt

FOLLOWUP_QUESTION_MAX_LENGTH = 1000
FOLLOWUP_CONTEXT_LABEL_MAX_LENGTH = 80
FOLLOWUP_CONTEXT_TEXT_MAX_LENGTH = 4000
FOLLOWUP_POLICY_REFUSAL_TEXT = (
    "这里只回答这道题相关的编程问题，请继续提问代码、输入输出、变量、循环、判断或调试相关的问题。"
)
FOLLOWUP_POLICY_MODEL_NAME = "policy-guardrail"
_PROGRAMMING_HINTS = (
    "代码",
    "程序",
    "编程",
    "题目",
    "输入",
    "输出",
    "样例",
    "变量",
    "数组",
    "字符串",
    "整数",
    "循环",
    "判断",
    "条件",
    "语法",
    "算法",
    "复杂度",
    "调试",
    "报错",
    "错误",
    "边界",
    "下标",
    "函数",
    "递归",
    "二分",
    "排序",
    "模拟",
    "搜索",
    "图",
    "树",
    "队列",
    "栈",
    "哈希",
    "指针",
    "引用",
    "结构体",
    "类",
    "main",
    "return",
    "for",
    "while",
    "if",
    "else",
    "cin",
    "cout",
    "scanf",
    "printf",
    "vector",
    "string",
    "openjudge",
    "c++",
    "cpp",
    "wa",
    "tle",
    "mle",
    "re",
)
_OFF_TOPIC_HINTS = (
    "天气",
    "气温",
    "下雨",
    "吃什么",
    "午饭",
    "晚饭",
    "早餐",
    "电影",
    "明星",
    "八卦",
    "旅游",
    "景点",
    "情感",
    "恋爱",
    "表白",
    "减肥",
    "健身",
    "穿搭",
    "作文",
    "周记",
    "检讨",
    "歌词",
    "笑话",
    "星座",
    "彩票",
    "股票",
    "历史",
    "地理",
    "做梦",
    "天气怎么样",
)


@dataclass(slots=True)
class StudentFollowupPreparation:
    session: SubmissionFollowupSession | None
    payload: StudentFollowupPayload | None
    model_name: str
    policy_refusal_text: str | None = None


def validate_followup_form(question_text: str, context_label: str, context_text: str) -> list[str]:
    errors: list[str] = []
    if not question_text:
        errors.append("请输入这次想追问的问题。")
    if len(question_text) > FOLLOWUP_QUESTION_MAX_LENGTH:
        errors.append("追问内容不能超过 1000 个字符。")
    if len(context_label) > FOLLOWUP_CONTEXT_LABEL_MAX_LENGTH:
        errors.append("引用标题不能超过 80 个字符。")
    if len(context_text) > FOLLOWUP_CONTEXT_TEXT_MAX_LENGTH:
        errors.append("引用内容不能超过 4000 个字符。")
    return errors


def create_student_followup_exchange(
    submission: Submission,
    *,
    question_text: str,
    context_label: str,
    context_text: str,
) -> StudentFollowupResponse:
    preparation = prepare_student_followup(
        submission,
        question_text=question_text,
        context_label=context_label,
        context_text=context_text,
    )
    if preparation.policy_refusal_text:
        return record_followup_exchange(
            submission,
            preparation=preparation,
            student_content=question_text,
            context_label=context_label,
            context_text=context_text,
            assistant_content=preparation.policy_refusal_text,
            latency_ms=0,
        )

    ai_config = _ai_config()
    service = DeepSeekDiagnosisService(
        api_key=ai_config["api_key"],
        base_url=ai_config["base_url"],
        model_name=preparation.model_name,
        student_system_prompt=get_student_system_prompt(),
    )
    if preparation.payload is None:
        raise DiagnosisServiceError("追问上下文准备失败。")
    response = service.answer_student_followup(
        preparation.payload
    )

    return record_followup_exchange(
        submission,
        preparation=preparation,
        student_content=question_text,
        context_label=context_label,
        context_text=context_text,
        assistant_content=response.answer_text,
        latency_ms=response.latency_ms,
    )


def prepare_student_followup(
    submission: Submission,
    *,
    question_text: str,
    context_label: str,
    context_text: str,
) -> StudentFollowupPreparation:
    _ensure_followup_available(submission)

    session = submission.followup_session
    if _should_use_local_policy_refusal(
        question_text=question_text,
        context_label=context_label,
        context_text=context_text,
    ):
        return StudentFollowupPreparation(
            session=session,
            payload=None,
            model_name=FOLLOWUP_POLICY_MODEL_NAME,
            policy_refusal_text=FOLLOWUP_POLICY_REFUSAL_TEXT,
        )

    snapshot = submission.problem_snapshot
    hint_run = submission.latest_student_hint_run
    structured_result = hint_run.structured_result_json or {} if hint_run else {}
    conversation_history = [
        {"role": message.role, "content": message.content}
        for message in (session.messages if session else [])
    ]

    return StudentFollowupPreparation(
        session=session,
        payload=StudentFollowupPayload(
            student_name=submission.student_name,
            problem_url=submission.problem_url,
            problem_title=submission.problem_title,
            description_text=snapshot.description_text if snapshot else None,
            input_text=snapshot.input_text if snapshot else None,
            output_text=snapshot.output_text if snapshot else None,
            sample_input_text=snapshot.sample_input_text if snapshot else None,
            sample_output_text=snapshot.sample_output_text if snapshot else None,
            code_text=submission.code_text,
            current_hint_summary=structured_result.get("overall_assessment"),
            current_hint_issues=structured_result.get("possible_issues") or [],
            question_text=question_text,
            selected_context_label=context_label or None,
            selected_context_text=context_text or None,
            conversation_history=conversation_history,
        ),
        model_name=_ai_config()["model_name"],
    )


def record_followup_exchange(
    submission: Submission,
    *,
    preparation: StudentFollowupPreparation,
    student_content: str,
    context_label: str,
    context_text: str,
    assistant_content: str,
    latency_ms: int,
) -> StudentFollowupResponse:
    session = preparation.session
    if session is None:
        session = SubmissionFollowupSession(submission=submission)
        db.session.add(session)
        db.session.flush()

    db.session.add(
        SubmissionFollowupMessage(
            session=session,
            role="student",
            content=student_content,
            context_label=context_label or None,
            context_text=context_text or None,
        )
    )
    db.session.add(
        SubmissionFollowupMessage(
            session=session,
            role="assistant",
            content=assistant_content,
            model_name=preparation.model_name,
            latency_ms=latency_ms,
        )
    )
    session.touch()
    db.session.commit()
    return StudentFollowupResponse(
        answer_text=assistant_content,
        raw_content=assistant_content,
        latency_ms=latency_ms,
        model_name=preparation.model_name,
    )


def _ensure_followup_available(submission: Submission) -> None:
    if submission.submission_mode != "self_check":
        raise ValueError("只有自己提交的记录才支持继续追问。")

    if submission.latest_student_hint_run is None or submission.latest_student_hint_run.status != "success":
        raise ValueError("请先等待学生提示生成成功，再继续追问。")

    if submission.problem_snapshot is None:
        raise ValueError("题面快照还没有准备好，请稍后再试。")


def _should_use_local_policy_refusal(*, question_text: str, context_label: str, context_text: str) -> bool:
    if context_label.strip() or context_text.strip():
        return False

    normalized_question = _normalize_text(question_text)
    if _contains_programming_signal(normalized_question):
        return False

    if any(keyword in normalized_question for keyword in _OFF_TOPIC_HINTS):
        return True

    return False


def _contains_programming_signal(text: str) -> bool:
    if any(keyword in text for keyword in _PROGRAMMING_HINTS):
        return True
    return bool(re.search(r"[{};#]|main\s*\(|cout|cin|scanf|printf", text))


def _normalize_text(value: str) -> str:
    return str(value).strip().lower()


__all__ = [
    "DiagnosisServiceError",
    "FOLLOWUP_POLICY_REFUSAL_TEXT",
    "create_student_followup_exchange",
    "prepare_student_followup",
    "record_followup_exchange",
    "validate_followup_form",
]


def _ai_config() -> dict[str, str]:
    return {
        "api_key": str(
            current_app.config.get("AI_API_KEY") or current_app.config.get("DEEPSEEK_API_KEY") or ""
        ).strip(),
        "base_url": str(
            current_app.config.get("AI_BASE_URL")
            or current_app.config.get("DEEPSEEK_BASE_URL")
            or "https://api.deepseek.com"
        ).strip(),
        "model_name": get_active_ai_model(),
    }
