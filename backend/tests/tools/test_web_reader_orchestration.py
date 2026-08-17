import asyncio

from chat_agents.tools.web_reader.orchestration import (
    FALLBACK_TRUNCATE_CHARS,
    build_document,
    count_tokens,
    normalize_markdown,
    parse_section_indices,
    parse_sections,
)
from chat_agents.tools.web_reader.tool import run as web_reader_run


def test_normalize_markdown_collapses_blank_lines_and_trailing_whitespace():
    raw = "# 标题   \r\n\r\n\r\n\r\n正文\r\n"

    normalized = normalize_markdown(raw)

    assert normalized == "# 标题\n\n正文"


def test_parse_sections_splits_on_headings_and_numbers_sequentially():
    markdown = "# 一\n第一节内容\n\n## 二\n第二节内容\n\n# 三\n第三节内容"

    sections = parse_sections(markdown)

    assert [s.index for s in sections] == [1, 2, 3]
    assert [s.title for s in sections] == ["一", "二", "三"]
    assert sections[0].level == 1
    assert sections[1].level == 2
    assert "第一节内容" in sections[0].content
    assert "第二节内容" not in sections[0].content


def test_parse_sections_returns_empty_when_no_headings():
    assert parse_sections("没有任何标题的纯文本") == []


def test_parse_section_indices_ignores_non_numeric_junk():
    assert parse_section_indices("3, 5, x") == [3, 5]


def test_short_document_returns_full_text_untouched():
    doc = build_document("https://a.example", "# 标题\n短正文")

    from chat_agents.tools.web_reader.orchestration import assemble_result

    result = assemble_result(doc, None)

    assert result.structured["mode"] == "full"
    assert result.structured["truncated"] is False
    assert result.model_text == doc.markdown


def test_long_document_with_headings_returns_structure_and_first_section():
    from chat_agents.tools.web_reader.orchestration import assemble_result

    section_body = "内容 " * 2000  # 足够撑过 8K token 阈值
    markdown = f"# 第一节\n{section_body}\n\n# 第二节\n{section_body}"
    doc = build_document("https://a.example", markdown)
    assert doc.token_count > 8_000

    result = assemble_result(doc, None)

    assert result.structured["mode"] == "structure"
    assert result.structured["section_count"] == 2
    assert "第一节" in result.model_text
    assert "第二节" in result.model_text  # 目录里出现，但正文只给第一节
    assert result.model_text.count(section_body.rstrip()) == 1


def test_section_request_returns_only_requested_sections_verbatim():
    from chat_agents.tools.web_reader.orchestration import assemble_result

    section_body = "内容 " * 2000
    markdown = f"# 一\n{section_body}\n\n# 二\n第二节独有文本\n\n# 三\n{section_body}"
    doc = build_document("https://a.example", markdown)

    result = assemble_result(doc, "2")

    assert "第二节独有文本" in result.model_text
    assert section_body.rstrip() not in result.model_text
    assert result.structured["mode"] == "sections"


def test_fallback_path_truncates_and_labels_it_honestly():
    from chat_agents.tools.web_reader.orchestration import assemble_result

    long_text = "没有标题的长网页 " * 5000
    doc = build_document("https://a.example", long_text)
    assert doc.sections == []
    assert doc.token_count > 8_000

    result = assemble_result(doc, None)

    assert result.structured["mode"] == "truncated"
    assert result.structured["truncated"] is True
    assert result.model_text.startswith("[内容已截断：全文约")
    assert len(doc.markdown) > FALLBACK_TRUNCATE_CHARS


def test_count_tokens_is_a_pure_deterministic_function():
    assert count_tokens("hello world") == count_tokens("hello world")
    assert count_tokens("") == 0


def test_build_document_applies_calibration_to_token_counts():
    markdown = "# 一\n" + "内容 " * 100

    uncalibrated = build_document("https://a.example", markdown)
    calibrated = build_document("https://a.example", markdown, calibration=1.5)

    assert calibrated.token_count > uncalibrated.token_count
    assert calibrated.sections[0].token_count > uncalibrated.sections[0].token_count


def test_run_memoizes_the_fetched_document_across_calls_in_one_run():
    fetch_calls = []

    class FakePort:
        def __init__(self, http_client, api_key=None):
            pass

        async def fetch(self, url):
            fetch_calls.append(url)
            return "# 一\n正文一\n\n# 二\n正文二"

    class FakeCtx:
        run_id = "run-1"
        http_client = object()
        token_calibration = 1.0

        def __init__(self):
            self._memo = {}

        def memo_get(self, key):
            return self._memo.get(key)

        def memo_set(self, key, value):
            self._memo[key] = value

    import chat_agents.tools.web_reader.tool as tool_module

    original_port = tool_module.JinaReaderPort
    tool_module.JinaReaderPort = FakePort
    try:
        ctx = FakeCtx()

        first = asyncio.run(web_reader_run({"url": "https://a.example"}, ctx))
        second = asyncio.run(web_reader_run({"url": "https://a.example", "section": "2"}, ctx))
    finally:
        tool_module.JinaReaderPort = original_port

    assert fetch_calls == ["https://a.example"]  # 第二次命中记忆化，没有再抓取
    assert "正文一" in first.model_text
    assert "正文二" in second.model_text
