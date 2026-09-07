"""Chat Agents backend package.

本地直起时把仓库根的 `.env` 读进 `os.environ`——Docker 路径下这件事由 compose 的
`environment:` 块做，本地没有人做（issue: 模型拉取失败）。密钥是机器属性、不进仓库
（ADR-0032），`endpoints.yaml` 只存 `auth_secret_ref` 变量名，值必须来自环境变量。

放在包的 `__init__.py` 而不是 `main.py`：`database.py` 在导入期就用 `DATABASE_URL`
建好了引擎，`main.py` 顶部的调用已经晚于那次导入，`.env` 里的 `DATABASE_URL` 会被
静默忽略。包初始化早于任何子模块，是唯一能覆盖全部导入路径的位置。
"""

from pathlib import Path

from dotenv import load_dotenv

# 锚在 __file__ 而非 cwd——uvicorn / pytest / alembic 可能从任意目录拉起。
_REPO_ROOT = Path(__file__).resolve().parents[3]

# override=False：已在环境里的值优先，compose 与 CI 注入的不会被文件覆盖；
# 生产镜像内没有 .env，此调用是空操作。
load_dotenv(_REPO_ROOT / ".env", override=False)

__all__: list[str] = []
