"""模型接入层的环境变量配置——两处配置中的第一处（ADR-0032）。

第二处是 YAML 端点配置文件本身（见 `server_config.py`），它描述有哪些档案、
各自什么协议；这里只决定去哪找那份文件。
"""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_ROOT = Path(__file__).resolve().parents[3]
_REPO_ROOT = _BACKEND_ROOT.parent
_DEFAULT_ENDPOINTS_CONFIG_PATH = _BACKEND_ROOT / "config" / "endpoints.yaml"
_DEFAULT_EVAL_REPORTS_DIR = _REPO_ROOT / ".eval-reports"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CHATAGENTS_", extra="ignore")

    endpoints_config_path: Path = Field(default=_DEFAULT_ENDPOINTS_CONFIG_PATH)
    model_discovery_enabled: bool = True
    eval_reports_dir: Path = Field(default=_DEFAULT_EVAL_REPORTS_DIR)
