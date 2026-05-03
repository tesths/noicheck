from flask import current_app

from ..extensions import db
from ..models import SystemSetting

AI_MODEL_SETTING_KEY = "active_ai_model"
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

    setting = db.session.get(SystemSetting, AI_MODEL_SETTING_KEY)
    if setting is None:
        setting = SystemSetting(key=AI_MODEL_SETTING_KEY, value=normalized)
        db.session.add(setting)
    else:
        setting.value = normalized
        setting.touch()
    return normalized
