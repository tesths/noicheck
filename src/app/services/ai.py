import json
import time
from dataclasses import dataclass

from openai import OpenAI

from ..schemas import DiagnosisResult

PROMPT_VERSION = "v1"


class DiagnosisServiceError(Exception):
    pass


@dataclass(slots=True)
class DiagnosisPayload:
    student_name: str
    problem_url: str
    problem_title: str | None
    description_text: str | None
    input_text: str | None
    output_text: str | None
    sample_input_text: str | None
    sample_output_text: str | None
    code_text: str


@dataclass(slots=True)
class DiagnosisResponse:
    result: DiagnosisResult
    raw_content: str
    latency_ms: int
    model_name: str


class DeepSeekDiagnosisService:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model_name: str,
        client: OpenAI | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self.client = client or OpenAI(api_key=api_key, base_url=self.base_url)

    def diagnose(self, payload: DiagnosisPayload) -> DiagnosisResponse:
        if not self.api_key:
            raise DiagnosisServiceError("未配置 DeepSeek API Key。")

        started_at = time.perf_counter()
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                temperature=0.2,
                response_format={"type": "json_object"},
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "请根据题目和学生程序，帮老师检查程序可能错在哪里。"
                            "不要假装运行过代码，只能根据题目和代码推断。"
                            "请输出严格 JSON，字段固定为 "
                            "overall_assessment, confidence, missing_context, "
                            "possible_issues, teacher_talking_points, next_step_checks。"
                            "possible_issues 最多 3 条，每条包含 title, evidence, explanation, suggested_fix。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": self._build_user_prompt(payload),
                    },
                ],
            )
        except Exception as exc:
            raise DiagnosisServiceError(f"调用 DeepSeek 失败：{exc}") from exc

        latency_ms = int((time.perf_counter() - started_at) * 1000)
        raw_content = response.choices[0].message.content or ""
        try:
            parsed = json.loads(raw_content)
        except json.JSONDecodeError as exc:
            raise DiagnosisServiceError("模型返回的内容不是合法 JSON。") from exc

        try:
            result = DiagnosisResult.model_validate(parsed)
        except Exception as exc:
            raise DiagnosisServiceError("模型返回 JSON 结构不符合预期。") from exc

        return DiagnosisResponse(
            result=result,
            raw_content=raw_content,
            latency_ms=latency_ms,
            model_name=self.model_name,
        )

    def _build_user_prompt(self, payload: DiagnosisPayload) -> str:
        return "\n\n".join(
            [
                "请你根据下面的题目和程序，检查程序可能错误的地方，并给出老师可直接转述的修改建议。",
                f"题目链接：{payload.problem_url}",
                f"题目标题：{payload.problem_title or '未知'}",
                f"题目描述：{payload.description_text or '未抓取到'}",
                f"输入格式：{payload.input_text or '未抓取到'}",
                f"输出格式：{payload.output_text or '未抓取到'}",
                f"样例输入：{payload.sample_input_text or '未抓取到'}",
                f"样例输出：{payload.sample_output_text or '未抓取到'}",
                f"学生：{payload.student_name}",
                "程序语言：C++",
                "程序：",
                payload.code_text,
            ]
        )
