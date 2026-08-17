"""模型接入层的配置错误。"""


class ConfigError(Exception):
    """端点配置存在结构错误。调用方应让它导致启动失败，而不是吞掉重试。"""


class ProfileUnavailableError(Exception):
    """请求解析的档案当前不可用（例如密钥未配置）。

    与 `ConfigError` 是两回事：这不是结构错误，不该让服务起不来——只是这一次
    解析拿不到可用档案，调用方按运行时错误处理。
    """
