"""工具定义只写一份 JSON Schema，三协议序列化差异归 ModelPort（issue #45）。"""

from chat_agents.llm.tool_schema import to_protocol_tools
from chat_agents.tools.types import ToolSpec

PARAMS = {
    "type": "object",
    "properties": {"query": {"type": "string"}},
    "required": ["query"],
}


async def _handler(_args: dict, _ctx: object) -> None:  # pragma: no cover - never called
    raise NotImplementedError


def _tool() -> ToolSpec:
    return ToolSpec(
        name="web_search",
        description="Search the web.",
        parameters=PARAMS,
        handler=_handler,
        timeout_s=10.0,
        retryable=True,
    )


def test_anthropic_shape_uses_input_schema() -> None:
    [serialized] = to_protocol_tools([_tool()], "anthropic_messages")
    assert serialized == {
        "name": "web_search",
        "description": "Search the web.",
        "input_schema": PARAMS,
    }


def test_openai_chat_completions_shape_wraps_in_function() -> None:
    [serialized] = to_protocol_tools([_tool()], "openai_chat_completions")
    assert serialized == {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web.",
            "parameters": PARAMS,
        },
    }


def test_openai_responses_shape_is_flat() -> None:
    [serialized] = to_protocol_tools([_tool()], "openai_responses")
    assert serialized == {
        "type": "function",
        "name": "web_search",
        "description": "Search the web.",
        "parameters": PARAMS,
    }


def test_parameters_are_the_same_object_across_protocols() -> None:
    """同一份 JSON Schema，不为任何协议重写。"""
    tool = _tool()
    anthropic = to_protocol_tools([tool], "anthropic_messages")[0]
    responses = to_protocol_tools([tool], "openai_responses")[0]
    chat = to_protocol_tools([tool], "openai_chat_completions")[0]
    assert anthropic["input_schema"] is tool.parameters
    assert responses["parameters"] is tool.parameters
    assert chat["function"]["parameters"] is tool.parameters


def test_empty_tool_list_serializes_to_empty_list() -> None:
    assert to_protocol_tools([], "anthropic_messages") == []


def test_registry_dict_definitions_serialize_identically_to_objects() -> None:
    """``tools.registry.tool_definitions()`` 产出的是字典，不是带属性的对象。

    只认属性会在运行期炸 ``'dict' object has no attribute 'name'``——这是真实
    故障：整条聊天链路每次运行都失败，而 ``Sequence[Any]`` 让 mypy 看不见。
    """

    tool = _tool()
    as_dict = {
        "name": tool.name,
        "description": tool.description,
        "parameters": tool.parameters,
    }

    for protocol in ("anthropic_messages", "openai_responses", "openai_chat_completions"):
        assert to_protocol_tools([as_dict], protocol) == to_protocol_tools([tool], protocol)
