from src.app.config import _normalize_database_url


def test_normalize_database_url_expands_relative_sqlite_path():
    normalized = _normalize_database_url("sqlite:///instance/dev.db")
    assert normalized.startswith("sqlite:////")
    assert normalized.endswith("/instance/dev.db")
