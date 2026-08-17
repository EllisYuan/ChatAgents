"""模型 API 协议——`base_url` 与 `protocol` 是正交选择，不能从模型标识推断。"""

from typing import Final, Literal

Protocol = Literal["openai_responses", "openai_chat_completions", "anthropic_messages"]

PROTOCOLS: Final[tuple[Protocol, ...]] = (
    "openai_responses",
    "openai_chat_completions",
    "anthropic_messages",
)

DEFAULT_PROTOCOL: Final[Protocol] = "openai_responses"
