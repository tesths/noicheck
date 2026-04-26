import json
from types import SimpleNamespace

import pytest

from src.app.services.ai import DeepSeekDiagnosisService, DiagnosisPayload, DiagnosisServiceError


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
                "correct_program": "#include <iostream>\nusing namespace std;\nint main(){return 0;}",
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
    assert "诊断原因" in call["messages"][1]["content"]
    assert "完整正确的 C++ 参考程序" in call["messages"][1]["content"]
    assert "简体中文" in call["messages"][1]["content"]
    assert result.result.possible_issues[0].title == "条件判断遗漏"


def test_deepseek_service_accepts_loose_chinese_json_shape():
    client = FakeClient()
    client.chat.completions.create = lambda **kwargs: SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=json.dumps(
                        {
                            "错误": "程序没有删除后缀，只是直接输出原单词。",
                            "修改建议": "补上对 er、ly、ing 后缀的判断和截断。",
                            "完整正确程序": "#include <iostream>\nusing namespace std;\nint main(){return 0;}",
                        },
                        ensure_ascii=False,
                    )
                )
            )
        ]
    )
    service = DeepSeekDiagnosisService(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model_name="deepseek-v4-pro",
        client=client,
    )

    result = service.diagnose(
        DiagnosisPayload(
            student_name="小明",
            problem_url="http://noi.openjudge.cn/ch0107/20/",
            problem_title="20:删除单词后缀",
            description_text="按要求删除单词后缀。",
            input_text="一个单词。",
            output_text="删除后缀后的结果。",
            sample_input_text="refer",
            sample_output_text="ref",
            code_text="int main() { return 0; }",
        )
    )

    assert result.result.overall_assessment == "程序没有删除后缀，只是直接输出原单词。"
    assert result.result.possible_issues[0].suggested_fix == "补上对 er、ly、ing 后缀的判断和截断。"


def test_deepseek_service_coerces_scalar_list_fields():
    client = FakeClient()
    client.chat.completions.create = lambda **kwargs: SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=json.dumps(
                        {
                            "overall_assessment": "程序没有实现后缀删除。",
                            "confidence": "high",
                            "missing_context": "缺少真实运行结果。",
                            "possible_issues": [
                                {
                                    "title": "核心逻辑缺失",
                                    "evidence": "代码直接输出输入值。",
                                    "explanation": "没有判断 er、ly、ing 后缀。",
                                    "suggested_fix": "补上字符串后缀判断。",
                                }
                            ],
                            "teacher_talking_points": "先让学生自己说出需要删除哪些后缀。",
                            "next_step_checks": "用 referer 和 happily 再测一次。",
                            "correct_program": "#include <iostream>\nusing namespace std;\nint main(){return 0;}",
                        },
                        ensure_ascii=False,
                    )
                )
            )
        ]
    )
    service = DeepSeekDiagnosisService(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model_name="deepseek-v4-pro",
        client=client,
    )

    result = service.diagnose(
        DiagnosisPayload(
            student_name="小明",
            problem_url="http://noi.openjudge.cn/ch0107/20/",
            problem_title="20:删除单词后缀",
            description_text="按要求删除单词后缀。",
            input_text="一个单词。",
            output_text="删除后缀后的结果。",
            sample_input_text="refer",
            sample_output_text="ref",
            code_text="int main() { return 0; }",
        )
    )

    assert result.result.missing_context == ["缺少真实运行结果。"]
    assert result.result.teacher_talking_points == ["先让学生自己说出需要删除哪些后缀。"]
    assert result.result.next_step_checks == ["用 referer 和 happily 再测一次。"]


def test_deepseek_service_accepts_correct_program_and_location_in_chinese_keys():
    client = FakeClient()
    client.chat.completions.create = lambda **kwargs: SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=json.dumps(
                        {
                            "overall_assessment": "程序的后缀判断分支写错了。",
                            "possible_issues": [
                                {
                                    "title": "后缀比较条件错误",
                                    "错误位置": "判断 er、ly、ing 的 if/else 分支",
                                    "evidence": "对字符串尾部的截取长度不对。",
                                    "explanation": "这样会把不该删除的字符也删掉。",
                                    "suggested_fix": "分别判断长度和尾部子串后再删除。",
                                }
                            ],
                            "完整正确程序": "#include <iostream>\nusing namespace std;\nint main(){return 0;}",
                        },
                        ensure_ascii=False,
                    )
                )
            )
        ]
    )
    service = DeepSeekDiagnosisService(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model_name="deepseek-v4-pro",
        client=client,
    )

    result = service.diagnose(
        DiagnosisPayload(
            student_name="小明",
            problem_url="http://noi.openjudge.cn/ch0107/20/",
            problem_title="20:删除单词后缀",
            description_text="按要求删除单词后缀。",
            input_text="一个单词。",
            output_text="删除后缀后的结果。",
            sample_input_text="refer",
            sample_output_text="ref",
            code_text="int main() { return 0; }",
        )
    )

    assert result.result.possible_issues[0].location == "判断 er、ly、ing 的 if/else 分支"
    assert result.result.correct_program.startswith("#include <iostream>")


def test_deepseek_service_requires_correct_program():
    client = FakeClient()
    client.chat.completions.create = lambda **kwargs: SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=json.dumps(
                        {
                            "overall_assessment": "程序逻辑有误。",
                            "possible_issues": [
                                {
                                    "title": "判断条件错误",
                                    "location": "主循环中的 if 分支",
                                    "evidence": "条件和题意不一致。",
                                    "explanation": "会导致结果错误。",
                                    "suggested_fix": "按题意重写判断条件。",
                                }
                            ],
                        },
                        ensure_ascii=False,
                    )
                )
            )
        ]
    )
    service = DeepSeekDiagnosisService(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model_name="deepseek-v4-pro",
        client=client,
    )

    with pytest.raises(DiagnosisServiceError):
        service.diagnose(
            DiagnosisPayload(
                student_name="小明",
                problem_url="http://noi.openjudge.cn/ch0107/20/",
                problem_title="20:删除单词后缀",
                description_text="按要求删除单词后缀。",
                input_text="一个单词。",
                output_text="删除后缀后的结果。",
                sample_input_text="refer",
                sample_output_text="ref",
                code_text="int main() { return 0; }",
            )
        )
