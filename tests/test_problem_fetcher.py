from src.app.services.problem_fetcher import ProblemFetchError, normalize_openjudge_url, parse_problem_html


def test_normalize_openjudge_url_accepts_expected_domain():
    assert normalize_openjudge_url("http://noi.openjudge.cn/ch0107/01/") == "http://noi.openjudge.cn/ch0107/01/"


def test_normalize_openjudge_url_rejects_other_domain():
    try:
        normalize_openjudge_url("https://example.com/ch0107/01/")
    except ProblemFetchError as exc:
        assert "仅支持" in str(exc)
    else:
        raise AssertionError("expected ProblemFetchError")


def test_parse_problem_html_extracts_core_sections():
    html = """
    <div id="pageTitle"><h2>01:统计数字字符个数</h2></div>
    <dl class="problem-content">
      <dt>描述</dt>
      <dd><p>输入一行字符，统计出其中数字字符的个数。</p></dd>
      <dt>输入</dt>
      <dd>一行字符串，总长度不超过255。</dd>
      <dt>输出</dt>
      <dd>输出字符串里面数字字符的个数。</dd>
      <dt>样例输入</dt>
      <dd><pre>Peking University is set up at 1898.</pre></dd>
      <dt>样例输出</dt>
      <dd><pre>4</pre></dd>
      <dt>来源</dt>
      <dd>习题(7-1)</dd>
    </dl>
    """

    result = parse_problem_html("http://noi.openjudge.cn/ch0107/01/", html)

    assert result.problem_path == "ch0107/01"
    assert result.title == "01:统计数字字符个数"
    assert "数字字符" in result.description_text
    assert result.sample_output_text == "4"
