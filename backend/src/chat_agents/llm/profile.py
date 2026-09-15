"""端点档案——一次模型调用所需的完整接入配置。

服务端预设与用户自定义两条构造路径交汇于此：两者产出的都是这一个 frozen dataclass。

``base_url`` 怎么解释由 ``address_mode`` 决定，规则集中在 ``endpoint_address.py``。
默认 ``sdk_native`` 是服务端预设那一层的既有行为（地址原样交给 SDK）；用户自定义
端点必须显式给出 ``auto`` 或 ``full``，不能继承这个默认值。
"""

from dataclasses import dataclass, field

from pydantic import SecretStr

from .endpoint_address import AddressMode
from .protocol import Protocol


@dataclass(frozen=True, slots=True)
class EndpointProfile:
    name: str
    protocol: Protocol
    base_url: str
    auth_field: str
    api_key: SecretStr
    address_mode: AddressMode = field(default="sdk_native")
