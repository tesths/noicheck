from urllib.parse import urlparse

from flask import current_app

from ..extensions import db
from ..models import SystemSetting
from .ai import DEFAULT_STUDENT_SYSTEM_PROMPT, DEFAULT_TEACHER_SYSTEM_PROMPT

AI_MODEL_SETTING_KEY = "active_ai_model"
TEACHER_SYSTEM_PROMPT_SETTING_KEY = "teacher_system_prompt"
STUDENT_SYSTEM_PROMPT_SETTING_KEY = "student_system_prompt"

# 后台设置和 AI_MODEL 使用与供应商无关的逻辑模型名，实际请求时按 AI_BASE_URL 解析成供应商模型 ID。
AI_MODEL_FLASH = "deepseek-flash"
AI_MODEL_PRO = "deepseek-pro"
ALLOWED_AI_MODELS = (AI_MODEL_FLASH, AI_MODEL_PRO)
DEFAULT_AI_MODEL = AI_MODEL_FLASH

# 历史配置和数据库里存的旧逻辑名，读取时统一归一到当前的逻辑模型名。
_LEGACY_AI_MODEL_ALIASES = {
    "deepseek-v4-flash": AI_MODEL_FLASH,
    "deepseek-v4-pro": AI_MODEL_PRO,
}

# 供应商实际模型 ID：OpenRouter 要求 provider/model 形式，DeepSeek 官方接口使用短名。
_PROVIDER_MODEL_IDS = {
    "openrouter": {
        # 2026-10-17 的最新 DeepSeek Flash 快照，DeepSeek 官方接口里叫 deepseek-flash。
        AI_MODEL_FLASH: "deepseek/deepseek-v4.1-flash-1017",
        AI_MODEL_PRO: "deepseek/deepseek-v4-pro",
    },
    "deepseek": {
        # DeepSeek 官方接口用短名：Flash 已确认是 deepseek-flash，Pro 按同一命名规则使用 deepseek-pro。
        AI_MODEL_FLASH: "deepseek-flash",
        AI_MODEL_PRO: "deepseek-pro",
    },
}

_OPENROUTER_HOST_SUFFIX = "openrouter.ai"
_DEEPSEEK_HOST_SUFFIX = "deepseek.com"


def _host_matches(host: str, suffix: str) -> bool:
    return host == suffix or host.endswith(f".{suffix}")


def normalize_ai_model_name(value: str | None) -> str:
    normalized = str(value or "").strip()
    if normalized in ALLOWED_AI_MODELS:
        return normalized
    return _LEGACY_AI_MODEL_ALIASES.get(normalized, "")


def default_ai_model_name() -> str:
    configured = normalize_ai_model_name(
        current_app.config.get("AI_MODEL") or current_app.config.get("DEEPSEEK_MODEL")
    )
    return configured or DEFAULT_AI_MODEL


def get_active_ai_model() -> str:
    setting = db.session.get(SystemSetting, AI_MODEL_SETTING_KEY)
    configured = normalize_ai_model_name(setting.value if setting else "")
    return configured or default_ai_model_name()


def set_active_ai_model(model_name: str) -> str:
    normalized = normalize_ai_model_name(model_name)
    if not normalized:
        raise ValueError("不支持的模型。")

    _set_setting_value(AI_MODEL_SETTING_KEY, normalized)
    return normalized


def resolve_ai_model_id(model_name: str | None, base_url: str | None) -> str:
    """把逻辑模型名按 AI_BASE_URL 解析成供应商实际使用的模型 ID。"""
    raw_name = str(model_name or "").strip()
    normalized = normalize_ai_model_name(raw_name) or default_ai_model_name()
    host = (urlparse(str(base_url or "")).hostname or "").lower()

    if _host_matches(host, _OPENROUTER_HOST_SUFFIX):
        return _PROVIDER_MODEL_IDS["openrouter"][normalized]
    if _host_matches(host, _DEEPSEEK_HOST_SUFFIX):
        return _PROVIDER_MODEL_IDS["deepseek"][normalized]
    # 其他 OpenAI 兼容网关：已经带 provider/model 形式的值原样使用，否则退回逻辑名。
    if "/" in raw_name:
        return raw_name
    return normalized


def active_ai_model_id() -> str:
    """当前后台模型按当前 AI_BASE_URL 解析后的供应商模型 ID。"""
    base_url = str(
        current_app.config.get("AI_BASE_URL")
        or current_app.config.get("DEEPSEEK_BASE_URL")
        or "https://api.deepseek.com"
    ).strip()
    return resolve_ai_model_id(get_active_ai_model(), base_url)


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
