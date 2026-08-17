"""端点档案——一次模型调用所需的完整接入配置。

服务端预设与用户自定义两条构造路径交汇于此：两者产出的都是这一个 frozen dataclass。
"""

from dataclasses import dataclass

from pydantic import SecretStr

from .protocol import Protocol


@dataclass(frozen=True, slots=True)
class EndpointProfile:
    name: str
    protocol: Protocol
    base_url: str
    auth_field: str
    api_key: SecretStr
