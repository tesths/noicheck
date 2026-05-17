from src.app import create_app
from src.app.services.job_queue import JobMessage, enqueue_job


class QueueConfig:
    TESTING = True
    SECRET_KEY = "test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {}
    WTF_CSRF_ENABLED = False
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_SECURE = False
    DEEPSEEK_API_KEY = "test-key"
    DEEPSEEK_BASE_URL = "https://api.deepseek.com"
    DEEPSEEK_MODEL = "deepseek-chat"
    ADMIN_INIT_USERNAME = ""
    ADMIN_INIT_PASSWORD = ""
    BOOTSTRAP_ON_STARTUP = False
    REQUIRE_PRODUCTION_ENV = False
    OPENJUDGE_REQUEST_TIMEOUT = 1
    SUBMISSION_CODE_MAX_LENGTH = 20000
    RATE_LIMIT_MAX_SUBMISSIONS = 20
    RATE_LIMIT_WINDOW_SECONDS = 300
    JOB_QUEUE_BACKEND = "vercel"
    VERCEL_QUEUE_REGION = "iad1"
    VERCEL_QUEUE_TOPIC = "noi_submission_jobs"
    VERCEL_OIDC_TOKEN = "queue-token"
    JOB_QUEUE_PUBLISH_TIMEOUT_SECONDS = 2.5
    INTERNAL_JOB_TOKEN = "test-internal-job-token"
    APP_BASE_URL = "http://localhost:5000"


def test_vercel_job_queue_reuses_http_client_and_respects_publish_timeout(monkeypatch):
    created_clients = []
    post_calls = []

    class ResponseStub:
        def raise_for_status(self):
            return None

    class ClientStub:
        def __init__(self, *, timeout):
            self.timeout = timeout
            created_clients.append(self)

        def post(self, url, *, json, headers):
            post_calls.append({"url": url, "json": json, "headers": headers, "timeout": self.timeout})
            return ResponseStub()

    monkeypatch.setattr("src.app.services.job_queue.httpx.Client", ClientStub)

    app = create_app(QueueConfig)
    message = JobMessage(
        job_type="fetch-and-student-diagnose",
        submission_public_id="sub-123",
        requested_by="student",
    )

    with app.app_context():
        enqueue_job(message, idempotency_key="idem-1")
        enqueue_job(message, idempotency_key="idem-2")

    assert len(created_clients) == 1
    assert len(post_calls) == 2
    assert post_calls[0]["timeout"] == 2.5
    assert post_calls[0]["url"] == "https://iad1.vercel-queue.com/api/v3/topic/noi_submission_jobs"
    assert post_calls[0]["headers"]["Authorization"] == "Bearer queue-token"
    assert post_calls[0]["headers"]["Vqs-Idempotency-Key"] == "idem-1"
    assert post_calls[1]["headers"]["Vqs-Idempotency-Key"] == "idem-2"
