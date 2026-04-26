from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed


class ProblemFetchError(Exception):
    pass


@dataclass(slots=True)
class ProblemContent:
    normalized_url: str
    problem_path: str
    title: str | None
    description_text: str | None
    input_text: str | None
    output_text: str | None
    sample_input_text: str | None
    sample_output_text: str | None
    source_text: str | None
    raw_excerpt: str | None


def normalize_openjudge_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise ProblemFetchError("题目链接必须以 http 或 https 开头。")
    if parsed.netloc.lower() != "noi.openjudge.cn":
        raise ProblemFetchError("当前仅支持 noi.openjudge.cn 题目链接。")

    path = parsed.path.rstrip("/")
    if not path:
        raise ProblemFetchError("题目链接缺少路径。")

    # OpenJudge 的 HTTPS 链路不稳定，本地和线上都优先走用户实际提供的 HTTP 入口。
    return f"http://noi.openjudge.cn{path}/"


def extract_problem_path(normalized_url: str) -> str:
    path = urlparse(normalized_url).path.strip("/")
    if not path:
        raise ProblemFetchError("无法识别题目路径。")
    return path


def _clean_text(value: str) -> str:
    lines = [line.strip() for line in value.replace("\r", "").splitlines()]
    compact = [line for line in lines if line]
    return "\n".join(compact).strip()


def _extract_dd_text(node) -> str:
    pre = node.find("pre")
    if pre is not None:
        return _clean_text(pre.get_text("\n"))
    return _clean_text(node.get_text("\n"))


def parse_problem_html(url: str, html: str) -> ProblemContent:
    normalized_url = normalize_openjudge_url(url)
    problem_path = extract_problem_path(normalized_url)
    soup = BeautifulSoup(html, "html.parser")

    title_node = soup.select_one("#pageTitle h2")
    title = _clean_text(title_node.get_text(" ")) if title_node else None

    content_dl = soup.select_one("dl.problem-content")
    if content_dl is None:
        raise ProblemFetchError("页面中未找到题面内容。")

    mapping: dict[str, str] = {}
    current_key: str | None = None
    for child in content_dl.children:
        name = getattr(child, "name", None)
        if name == "dt":
            current_key = _clean_text(child.get_text(" "))
        elif name == "dd" and current_key:
            mapping[current_key] = _extract_dd_text(child)

    description_text = mapping.get("描述")
    input_text = mapping.get("输入")
    output_text = mapping.get("输出")
    sample_input_text = mapping.get("样例输入")
    sample_output_text = mapping.get("样例输出")
    source_text = mapping.get("来源")

    raw_excerpt = "\n\n".join(
        part
        for part in [
            description_text,
            input_text,
            output_text,
            sample_input_text,
            sample_output_text,
        ]
        if part
    )

    return ProblemContent(
        normalized_url=normalized_url,
        problem_path=problem_path,
        title=title,
        description_text=description_text,
        input_text=input_text,
        output_text=output_text,
        sample_input_text=sample_input_text,
        sample_output_text=sample_output_text,
        source_text=source_text,
        raw_excerpt=raw_excerpt or None,
    )


class OpenJudgeProblemFetcher:
    def __init__(self, timeout: float = 10.0) -> None:
        self.timeout = timeout

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_fixed(1),
        retry=retry_if_exception_type((httpx.HTTPError, ProblemFetchError)),
        reraise=True,
    )
    def fetch(self, url: str) -> ProblemContent:
        normalized_url = normalize_openjudge_url(url)
        headers = {"User-Agent": "Mozilla/5.0"}
        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=True, headers=headers) as client:
                response = client.get(normalized_url)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProblemFetchError(f"抓取题面失败：{exc}") from exc
        return parse_problem_html(normalized_url, response.text)
