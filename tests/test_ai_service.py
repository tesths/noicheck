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
    assert "只输出一个 JSON 对象" in call["messages"][0]["content"]
    assert "不要输出 Markdown 代码块" in call["messages"][0]["content"]
    assert "第一个非空字符必须是 {" in call["messages"][0]["content"]
    assert "题目描述" in call["messages"][1]["content"]
    assert "诊断原因" in call["messages"][1]["content"]
    assert "完整正确的 C++ 参考程序" in call["messages"][1]["content"]
    assert "简体中文" in call["messages"][1]["content"]
    assert result.result.possible_issues[0].title == "条件判断遗漏"
    assert call["timeout"] == 30.0


def test_deepseek_service_uses_custom_teacher_system_prompt():
    client = FakeClient()
    service = DeepSeekDiagnosisService(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model_name="deepseek-v4-pro",
        client=client,
        teacher_system_prompt="老师自定义系统提示",
    )

    service.diagnose(
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
    assert call["messages"][0]["content"] == "老师自定义系统提示"
    assert "题目描述" in call["messages"][1]["content"]


@pytest.mark.parametrize("audience", ["teacher", "student"])
def test_deepseek_service_caps_total_prompt_payload_size(audience):
    service = DeepSeekDiagnosisService(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model_name="deepseek-v4-pro",
        client=FakeClient(),
        max_prompt_chars=120,
    )
    payload = DiagnosisPayload(
        student_name="小明",
        problem_url="https://noi.openjudge.cn/ch0107/01/",
        problem_title="01:统计数字字符个数",
        description_text="A" * 200,
        input_text="B" * 200,
        output_text="C" * 200,
        sample_input_text="D" * 200,
        sample_output_text="E" * 200,
        code_text="F" * 200,
    )

    prompt = service._build_user_prompt(payload, audience=audience)

    dynamic_char_count = (
        prompt.count("A")
        + prompt.count("B")
        + max(prompt.count("C") - 2, 0)
        + prompt.count("D")
        + prompt.count("E")
        + prompt.count("F")
    )
    assert dynamic_char_count <= 120
    assert "题目链接" in prompt
    assert "程序：" in prompt


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


def test_deepseek_service_accepts_json_wrapped_in_markdown_fence():
    client = FakeClient()
    client.chat.completions.create = lambda **kwargs: SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=(
                        "```json\n"
                        + json.dumps(
                            {
                                "overall_assessment": "程序没有删除后缀。",
                                "possible_issues": [
                                    {
                                        "title": "缺少后缀判断",
                                        "location": "主逻辑分支",
                                        "evidence": "代码直接输出原字符串。",
                                        "explanation": "没有按题意裁剪后缀。",
                                        "suggested_fix": "补上后缀判断。",
                                    }
                                ],
                                "correct_program": "#include <iostream>\nint main(){return 0;}",
                            },
                            ensure_ascii=False,
                        )
                        + "\n```"
                    )
                )
            )
        ]
    )
    service = DeepSeekDiagnosisService(
        api_key="test-key",
        base_url="https://openrouter.ai/api/v1",
        model_name="deepseek/deepseek-v4-pro",
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

    assert result.result.overall_assessment == "程序没有删除后缀。"


def test_deepseek_service_accepts_json_with_prefix_and_suffix_text():
    client = FakeClient()
    client.chat.completions.create = lambda **kwargs: SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=(
                        "下面是诊断结果：\n"
                        + json.dumps(
                            {
                                "overall_assessment": "边界判断有误。",
                                "possible_issues": [
                                    {
                                        "title": "循环边界错误",
                                        "location": "for 循环结束条件",
                                        "evidence": "可能漏掉最后一个字符。",
                                        "explanation": "边界值时会少统计一次。",
                                        "suggested_fix": "检查结束条件。",
                                    }
                                ],
                                "correct_program": "#include <iostream>\nint main(){return 0;}",
                            },
                            ensure_ascii=False,
                        )
                        + "\n请老师参考。"
                    )
                )
            )
        ]
    )
    service = DeepSeekDiagnosisService(
        api_key="test-key",
        base_url="https://openrouter.ai/api/v1",
        model_name="deepseek/deepseek-v4-pro",
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

    assert result.result.overall_assessment == "边界判断有误。"


def test_deepseek_service_retries_once_for_retryable_failure():
    class FlakyCompletions:
        def __init__(self):
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("temporary 429")
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=json.dumps(
                                {
                                    "overall_assessment": "重试后成功。",
                                    "confidence": "medium",
                                    "missing_context": [],
                                    "possible_issues": [],
                                    "teacher_talking_points": [],
                                    "next_step_checks": [],
                                    "correct_program": "#include <iostream>\nint main(){return 0;}",
                                },
                                ensure_ascii=False,
                            )
                        )
                    )
                ]
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=FlakyCompletions()))
    service = DeepSeekDiagnosisService(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model_name="deepseek-v4-pro",
        client=client,
        max_retries=1,
        retry_backoff_seconds=0,
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

    assert result.result.overall_assessment == "重试后成功。"
    assert client.chat.completions.calls == 2


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


def test_ai_service_raises_provider_neutral_error_when_api_key_missing():
    service = DeepSeekDiagnosisService(
        api_key="",
        base_url="https://api.deepseek.com",
        model_name="deepseek-v4-pro",
        client=FakeClient(),
    )

    with pytest.raises(DiagnosisServiceError, match="未配置 AI API Key。"):
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


def test_ai_service_raises_provider_neutral_error_when_client_call_fails():
    class FailingCompletions:
        def create(self, **kwargs):
            raise RuntimeError("boom")

    class FailingClient:
        def __init__(self):
            self.chat = SimpleNamespace(completions=FailingCompletions())

    service = DeepSeekDiagnosisService(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model_name="deepseek-v4-pro",
        client=FailingClient(),
    )

    with pytest.raises(DiagnosisServiceError, match="调用 AI 服务失败：boom"):
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
