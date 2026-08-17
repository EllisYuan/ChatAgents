from chat_agents.tools.web_search.orchestration import SearchHit, assemble_result, build_structured


def test_build_structured_carries_all_fields_for_the_span():
    hits = [SearchHit(title="标题", url="https://a.example", content="片段", score=0.9)]

    structured = build_structured("查询词", hits)

    assert structured == {
        "query": "查询词",
        "result_count": 1,
        "results": [{"title": "标题", "url": "https://a.example", "content": "片段", "score": 0.9}],
    }


def test_render_for_model_never_leaks_score_or_favicon():
    hits = [SearchHit(title="标题", url="https://a.example", content="片段", score=0.9)]

    result = assemble_result("查询词", hits)

    assert "0.9" not in result.model_text
    assert "https://a.example" in result.model_text
    assert "标题" in result.model_text


def test_assemble_result_with_no_hits_says_so():
    result = assemble_result("没有结果的查询", [])

    assert result.structured["result_count"] == 0
    assert "没有找到结果" in result.model_text
