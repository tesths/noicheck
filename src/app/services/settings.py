from flask import current_app

from ..extensions import db
from ..models import SystemSetting
from .ai import DEFAULT_STUDENT_SYSTEM_PROMPT, DEFAULT_TEACHER_SYSTEM_PROMPT

AI_MODEL_SETTING_KEY = "active_ai_model"
TEACHER_SYSTEM_PROMPT_SETTING_KEY = "teacher_system_prompt"
STUDENT_SYSTEM_PROMPT_SETTING_KEY = "student_system_prompt"
ALLOWED_AI_MODELS = ("deepseek-v4-flash", "deepseek-v4-pro")


def default_ai_model_name() -> str:
    configured = (
        str(current_app.config.get("AI_MODEL") or current_app.config.get("DEEPSEEK_MODEL") or "").strip()
    )
    if configured in ALLOWED_AI_MODELS:
        return configured
    return "deepseek-v4-pro"


def get_active_ai_model() -> str:
    setting = db.session.get(SystemSetting, AI_MODEL_SETTING_KEY)
    configured = str(setting.value).strip() if setting and setting.value else ""
    if configured in ALLOWED_AI_MODELS:
        return configured
    return default_ai_model_name()


def set_active_ai_model(model_name: str) -> str:
    normalized = str(model_name).strip()
    if normalized not in ALLOWED_AI_MODELS:
        raise ValueError("不支持的模型。")

    _set_setting_value(AI_MODEL_SETTING_KEY, normalized)
    return normalized


def get_teacher_system_prompt() -> str:
    return _get_text_setting(TEACHER_SYSTEM_PROMPT_SETTING_KEY, DEFAULT_TEACHER_SYSTEM_PROMPT)


def get_student_system_prompt() -> str:
    return _get_text_setting(STUDENT_SYSTEM_PROMPT_SETTING_KEY, DEFAULT_STUDENT_SYSTEM_PROMPT)


def set_teacher_system_prompt(prompt: str) -> str:
    normalized = _normalize_required_text(prompt)
    _set_setting_value(TEACHER_SYSTEM_PROMPT_SETTING_KEY, normalized)
    return normalized


def set_student_system_prompt(prompt: str) -> str:
    normalized = _normalize_required_text(prompt)
    _set_setting_value(STUDENT_SYSTEM_PROMPT_SETTING_KEY, normalized)
    return normalized


def set_ai_prompts(*, teacher_system_prompt: str, student_system_prompt: str) -> dict[str, str]:
    teacher_prompt = _normalize_required_text(teacher_system_prompt)
    student_prompt = _normalize_required_text(student_system_prompt)
    _set_setting_value(TEACHER_SYSTEM_PROMPT_SETTING_KEY, teacher_prompt)
    _set_setting_value(STUDENT_SYSTEM_PROMPT_SETTING_KEY, student_prompt)
    return {
        "teacher_system_prompt": teacher_prompt,
        "student_system_prompt": student_prompt,
    }


def _get_text_setting(key: str, default_value: str) -> str:
    configured = _get_setting_value(key)
    return configured or default_value


def _get_setting_value(key: str) -> str:
    setting = db.session.get(SystemSetting, key)
    return str(setting.value).strip() if setting and setting.value else ""


def _set_setting_value(key: str, value: str) -> None:
    setting = db.session.get(SystemSetting, key)
    if setting is None:
        setting = SystemSetting(key=key, value=value)
        db.session.add(setting)
        return
    setting.value = value
    setting.touch()


def _normalize_required_text(value: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError("设置值不能为空。")
    return normalized
