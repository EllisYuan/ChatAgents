"""前端开发命令转发入口。"""

from __future__ import annotations

import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    web = runpy.run_path(str(ROOT / "scripts/dev.py"))["web"]
    web()
