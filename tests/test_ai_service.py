import json
from types import SimpleNamespace

from src.app.services.ai import DeepSeekDiagnosisService, DiagnosisPayload


class FakeCompletions:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        content = json.dumps(
            {
                "overall_assessment": "更像是边界判断没有写对。",
                "confidence": "medium",
                "missing_context": [],
                "possible_issues": [
                    {
                        "title": "条件判断遗漏",
                        "evidence": "代码里没有处理输入为空的分支。",
                        "explanation": "边界值时会得到错误结果。",
                        "suggested_fix": "补上空字符串或最小输入时的判断。",
                    }
                ],
                "teacher_talking_points": ["先让学生自己用边界样例手算一遍。"],
                "next_step_checks": ["用最小输入和样例重新检查输出。"],
            },
            ensure_ascii=False,
        )
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )


class FakeClient:
    def __init__(self):
        self.chat = SimpleNamespace(completions=FakeCompletions())


def test_deepseek_service_uses_simple_chat_completion():
    client = FakeClient()
    service = DeepSeekDiagnosisService(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model_name="deepseek-v4-pro",
        client=client,
    )

    result = service.diagnose(
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
    assert call["model"] == "deepseek-v4-pro"
    assert "reasoning_effort" not in call
    assert "extra_body" not in call
    assert "题目描述" in call["messages"][1]["content"]
    assert result.result.possible_issues[0].title == "条件判断遗漏"
