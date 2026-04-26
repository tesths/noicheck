from src.app.extensions import db
from src.app.models import AdminUser
from src.app.services.auth import authenticate_admin, hash_client_ip, hash_password


def test_authenticate_admin_returns_user(app):
    with app.app_context():
        admin = AdminUser(username="teacher", password_hash=hash_password("pass123"))
        db.session.add(admin)
        db.session.commit()

        authenticated = authenticate_admin("teacher", "pass123")

        assert authenticated is not None
        assert authenticated.username == "teacher"


def test_hash_client_ip_is_stable():
    assert hash_client_ip("127.0.0.1") == hash_client_ip("127.0.0.1")

