#!/usr/bin/env python3

import os
import sys

from sqlalchemy import create_engine

from src.app.config import _normalize_database_url
from src.app.services.migration_state import prepare_legacy_alembic_version


def main() -> int:
    raw_database_url = (
        os.getenv("DATABASE_URL", "").strip() or os.getenv("MIGRATION_DATABASE_URL", "").strip()
    )
    if not raw_database_url:
        print("DATABASE_URL 未设置，跳过历史迁移状态准备。")
        return 0

    engine = create_engine(_normalize_database_url(raw_database_url))
    try:
        revisions = prepare_legacy_alembic_version(engine)
    finally:
        engine.dispose()

    if revisions:
        print("已为历史数据库写入 Alembic 基线：", ", ".join(revisions))
    else:
        print("不需要补写 Alembic 基线。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
