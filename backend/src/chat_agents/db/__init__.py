"""ORM 模型包——导入子模块以把表挂到 ``Base.metadata`` 上（issue #48）。"""

from . import app, obs

__all__ = ["app", "obs"]
