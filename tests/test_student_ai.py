import json
from types import SimpleNamespace

from src.app.extensions import db
from src.app.models import DiagnosisRun, Submission, StudentUser
from src.app.schemas import StudentHintResult
from src.app.services.ai import (
    DeepSeekDiagnosisService,
    DiagnosisPayload,
    StudentHintResponse,
)
from src.app.services.problem_fetcher import ProblemContent
from src.app.services.auth import hash_password


class FakeCompletions:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        content = json.dumps(
            {
                "overall_assessment": "整体思路接近了，但循环边界要再核对。",
                "confidence": "medium",
                "possible_issues": [
                    {
                        "title": "可能漏掉最后一个字符",
                        "location": "主循环结束条件",
                        "evidence": "边界值输入时可能少统计一次。",
                        "explanation": "如果循环提前结束，尾部数字不会被计入。",
                        "suggested_fix": "重点检查下标递增和循环终止条件。",
                    }
                ],
                "next_step_checks": ["先手算 abc123 和 000 的结果。"],
                "encouragement_or_strategy": "先定位问题，再改最小一处代码。",
                "correct_program": "#include <iostream>\nint main(){return 0;}",
            },
            ensure_ascii=False,
        )
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )


class FakeClient:
    def __init__(self):
        self.chat = SimpleNamespace(completions=FakeCompletions())


def _auth_headers() -> dict[str, str]:
    return {"X-Internal-Job-Token": "test-internal-job-token"}


def test_deepseek_service_generates_student_hint_without_reference_program():
    client = FakeClient()
    service = DeepSeekDiagnosisService(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model_name="deepseek-v4-pro",
        client=client,
    )

    result = service.diagnose_student(
        DiagnosisPayload(
            student_name="小明",
            problem_url="https://noi.openjudge.cn/ch0107/01/",
            problem_title="01:统计数字字符个数",
            description_text="输入一行字符，统计其中数字字符的个数。",
            input_text="一行字符串。",
            output_text="输出数字字符个数。",
            sample_input_text="abc123",
            sample_output_text="3",
            code_text="int main() { return 0; }",
        )
    )

    call = client.chat.completions.calls[0]
    assert "正确答案" in call["messages"][0]["content"]
    assert "一步一步引导学生" in call["messages"][0]["content"]
    assert "先用一句简短的话给出总体提示诊断" in call["messages"][0]["content"]
    assert "用小学生也能听懂的话" in call["messages"][0]["content"]
    assert "如果学生提交的内容明显不是 C++ 程序" in call["messages"][0]["content"]
    assert "这里只能提交题目对应的程序代码" in call["messages"][0]["content"]
    assert "明确告诉学生下一步先做什么" in call["messages"][0]["content"]
    assert "语气要真诚、温和、鼓励" in call["messages"][0]["content"]
    assert "完整正确的 C++ 参考程序" not in call["messages"][1]["content"]
    assert isinstance(result, StudentHintResponse)
    assert isinstance(result.result, StudentHintResult)
    assert result.result.encouragement_or_strategy == "先定位问题，再改最小一处代码。"
    assert "correct_program" not in result.result.model_dump()


def test_internal_job_endpoint_processes_student_hint_job(app, client, monkeypatch):
    def fake_fetch(self, url):
        return ProblemContent(
            normalized_url="http://noi.openjudge.cn/ch0107/01/",
            problem_path="ch0107/01",
            title="01:统计数字字符个数",
            description_text="desc",
            input_text="input",
            output_text="output",
            sample_input_text="abc123",
            sample_output_text="3",
            source_text="source",
            raw_excerpt="desc\ninput\noutput",
        )

    def fake_diagnose_student(self, payload):
        return StudentHintResponse(
            result=StudentHintResult.model_validate(
                {
                    "overall_assessment": "先检查循环边界。",
                    "confidence": "medium",
                    "possible_issues": [
                        {
                            "title": "循环边界可能不对",
                            "location": "主循环结束条件",
                            "evidence": "可能漏掉最后一个字符。",
                            "explanation": "这会让尾部数字没有被统计。",
                            "suggested_fix": "先用样例逐步模拟循环。",
                        }
                    ],
                    "next_step_checks": ["手算 abc123 和 0。"],
                    "encouragement_or_strategy": "先模拟，再局部修改。",
                }
            ),
            raw_content="{}",
            latency_ms=88,
            model_name="deepseek-v4-pro",
        )

    monkeypatch.setattr("src.app.services.jobs.OpenJudgeProblemFetcher.fetch", fake_fetch)
    monkeypatch.setattr("src.app.services.jobs.DeepSeekDiagnosisService.diagnose_student", fake_diagnose_student)

    with app.app_context():
        student = StudentUser(nickname="小明", password_hash=hash_password("pw-1"))
        submission = Submission(
            student_name="小明",
            student_user=student,
            problem_url="http://noi.openjudge.cn/ch0107/01/",
            code_text="int main() { return 0; }",
            fetch_status="queued",
            student_hint_status="queued",
            diagnosis_status="pending",
        )
        db.session.add_all([student, submission])
        db.session.commit()
        public_id = submission.public_id

    response = client.post(
        "/internal/jobs/process",
        json={"job_type": "fetch-and-student-diagnose", "submission_public_id": public_id},
        headers=_auth_headers(),
    )

    assert response.status_code == 200
    assert response.json == {"ok": True, "status": "success"}

    with app.app_context():
        submission = Submission.query.filter_by(public_id=public_id).one()
        student_runs = DiagnosisRun.query.filter_by(submission_id=submission.id, audience="student").all()

        assert submission.fetch_status == "success"
        assert submission.student_hint_status == "success"
        assert submission.diagnosis_status == "pending"
        assert submission.latest_student_hint_run.status == "success"
        assert submission.latest_student_hint_run.prompt_version == "student-v3"
        assert submission.latest_diagnosis_run is None
        assert len(student_runs) == 1


def test_internal_job_endpoint_records_provider_neutral_ai_failure_message(app, client, monkeypatch):
    def fake_fetch(self, url):
        return ProblemContent(
            normalized_url="http://noi.openjudge.cn/ch0107/01/",
            problem_path="ch0107/01",
            title="01:统计数字字符个数",
            description_text="desc",
            input_text="input",
            output_text="output",
            sample_input_text="abc123",
            sample_output_text="3",
            source_text="source",
            raw_excerpt="desc\ninput\noutput",
        )

    monkeypatch.setattr("src.app.services.jobs.OpenJudgeProblemFetcher.fetch", fake_fetch)

    with app.app_context():
        app.config["AI_API_KEY"] = ""
        app.config["DEEPSEEK_API_KEY"] = ""
        student = StudentUser(nickname="小明", password_hash=hash_password("pw-1"))
        submission = Submission(
            student_name="小明",
            student_user=student,
            problem_url="http://noi.openjudge.cn/ch0107/01/",
            code_text="int main() { return 0; }",
            fetch_status="queued",
            student_hint_status="queued",
            diagnosis_status="pending",
        )
        db.session.add_all([student, submission])
        db.session.commit()
        public_id = submission.public_id

    response = client.post(
        "/internal/jobs/process",
        json={"job_type": "fetch-and-student-diagnose", "submission_public_id": public_id},
        headers=_auth_headers(),
    )

    assert response.status_code == 200
    assert response.json == {"ok": True, "status": "failed"}

    with app.app_context():
        submission = Submission.query.filter_by(public_id=public_id).one()
        student_run = DiagnosisRun.query.filter_by(submission_id=submission.id, audience="student").one()

        assert submission.fetch_status == "success"
        assert submission.student_hint_status == "failed"
        assert "AI API Key" in student_run.error_message
        assert "DeepSeek" not in student_run.error_message
