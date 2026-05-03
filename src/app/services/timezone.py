from datetime import datetime, timezone
from zoneinfo import ZoneInfo


BEIJING_TIMEZONE = ZoneInfo("Asia/Shanghai")


def to_beijing_time(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(BEIJING_TIMEZONE)


def format_beijing_time(value: datetime | None, fmt: str = "%Y-%m-%d %H:%M") -> str:
    localized = to_beijing_time(value)
    if localized is None:
        return "-"
    return localized.strftime(fmt)
