import json

from src.app.extensions import db
from src.app.models import Submission, SubmissionFollowupMessage, SubmissionFollowupSession, StudentUser
from src.app.services.auth import hash_password


def test_clean_followup_history_command_normalizes_legacy_assistant_json(app):
    with app.app_context():
        student = StudentUser(nickname="owner", password_hash=hash_password("pw-1"))
        submission = Submission(
            student_name="owner",
            student_user=student,
            problem_url="http://noi.openjudge.cn/ch0107/03/",
            code_text="int main() { return 0; }",
            submission_mode="self_check",
            fetch_status="success",
            student_hint_status="success",
            diagnosis_status="pending",
        )
        session = SubmissionFollowupSession(submission=submission)
        legacy_json = json.dumps(
            {
                "overall_assessment": "先检查循环结束条件，它现在只会让 i 取到 0。",
                "confidence": "high",
                "possible_issues": [
                    {
                        "title": "循环结束条件写死了",
                        "location": "for(int i=0;i<=0;i++)",
                        "evidence": "第一次循环后 i 变成 1，1<=0 立刻不成立。",
                        "explanation": "中间那个条件决定循环还能不能继续，所以它不能一直写死在 0 上。",
                        "suggested_fix": "如果要遍历字符串，就把条件改成和字符串长度比较，比如 i < dna1.length()。",
                    }
                ],
                "next_step_checks": ["先把输入改成两个 DNA 字符串变量。"],
                "encouragement_or_strategy": "先只改这一处循环条件，不要一下子全重写。",
            },
            ensure_ascii=False,
        )
        db.session.add_all([student, submission, session])
        db.session.flush()
        db.session.add_all(
            [
                SubmissionFollowupMessage(
                    session=session,
                    role="student",
                    content="为什么这里会少算一次？",
                ),
                SubmissionFollowupMessage(
                    session=session,
                    role="assistant",
                    content=legacy_json,
                    model_name="deepseek-v4-flash",
                ),
                SubmissionFollowupMessage(
                    session=session,
                    role="assistant",
                    content="你先手推最后一轮循环。",
                    model_name="deepseek-v4-flash",
                ),
            ]
        )
        db.session.commit()

    runner = app.test_cli_runner()

    result = runner.invoke(args=["clean-followup-history"])

    assert result.exit_code == 0
    assert "已更新 1 条历史追问消息" in result.output

    with app.app_context():
        messages = SubmissionFollowupMessage.query.order_by(SubmissionFollowupMessage.id.asc()).all()
        assert messages[0].content == "为什么这里会少算一次？"
        assert messages[1].content.startswith("先检查循环结束条件，它现在只会让 i 取到 0。")
        assert "先盯住：循环结束条件写死了" in messages[1].content
        assert messages[2].content == "你先手推最后一轮循环。"

    second_result = runner.invoke(args=["clean-followup-history"])

    assert second_result.exit_code == 0
    assert "已更新 0 条历史追问消息" in second_result.output
