"""``structlog`` 一次性配置（issue #52）。

日志只记跨运行的系统事件，不记「一次运行内部发生了什么」——那归跨度
（``obs.span``）。流式路径每次运行最多打 0~1 条日志，且日志正文不带模型
输出的文本内容。
"""

from __future__ import annotations

import logging

import structlog


def configure_logging() -> None:
    logging.basicConfig(format="%(message)s", level=logging.INFO)
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
