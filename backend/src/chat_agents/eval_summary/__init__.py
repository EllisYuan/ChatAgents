"""站点级评测展示面（issue #66，ADR-0028）。

只读，只从磁盘上的评测产出文件读四个数字，从不在本包内跑评测、从不硬编码
分数。数据落地路径属于评测 CI 管线（``backend/tests/evals``），本包只负责
读取与呈现。
"""

from __future__ import annotations
