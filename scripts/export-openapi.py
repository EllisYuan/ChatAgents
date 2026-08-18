"""导出当前 FastAPI app.openapi()，供前端 CI 类型生成使用。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from chat_agents.main import app


if len(sys.argv) != 2:
    raise SystemExit("用法：python scripts/export-openapi.py <输出路径>")

output_path = Path(sys.argv[1])
output_path.parent.mkdir(parents=True, exist_ok=True)
output_path.write_text(json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
