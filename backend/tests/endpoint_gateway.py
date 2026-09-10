"""Loopback HTTP 上游：路由由测试显式指定，SDK 与 ModelPort 保持真实。"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from chat_agents.llm.protocol import Protocol

MODEL = "fixture-main"
AUXILIARY_MODEL = "fixture-auxiliary"
API_KEY = "fixture-only-secret"
ANSWER = "fixture answer"


def _sse(protocol: Protocol, model: str) -> bytes:
    if protocol == "openai_chat_completions":
        chunks = [
            {
                "id": "fixture",
                "object": "chat.completion.chunk",
                "created": 0,
                "model": model,
                "choices": [{"index": 0, "delta": {"content": ANSWER}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            }
        ]
    elif protocol == "openai_responses":
        chunks = [
            {
                "type": "response.completed",
                "sequence_number": 0,
                "response": {
                    "id": "fixture",
                    "created_at": 0,
                    "model": model,
                    "object": "response",
                    "output": [
                        {
                            "id": "msg_1",
                            "type": "message",
                            "status": "completed",
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": ANSWER,
                                    "annotations": [],
                                    "logprobs": None,
                                }
                            ],
                        }
                    ],
                    "parallel_tool_calls": True,
                    "tool_choice": "auto",
                    "tools": [],
                    "status": "completed",
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": 5,
                        "total_tokens": 15,
                        "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
                        "output_tokens_details": {"reasoning_tokens": 0},
                    },
                },
            }
        ]
    else:
        chunks = [
            {
                "type": "message_start",
                "message": {
                    "id": "fixture",
                    "type": "message",
                    "role": "assistant",
                    "content": [],
                    "model": model,
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 10, "output_tokens": 0},
                },
            },
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": ANSWER},
            },
            {"type": "content_block_stop", "index": 0},
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                "usage": {"output_tokens": 5},
            },
            {"type": "message_stop"},
        ]
    body = "".join(
        (f"event: {chunk['type']}\n" if "type" in chunk else "")
        + "data: "
        + json.dumps(chunk)
        + "\n\n"
        for chunk in chunks
    )
    if protocol == "openai_chat_completions":
        body += "data: [DONE]\n\n"
    return body.encode()


@dataclass
class Gateway:
    origin: str = ""
    requests: list[tuple[str, str, str | None]] = field(default_factory=list)
    # 改写生成 URL 不能顺带改掉鉴权头或 body——这两样留在这里供断言。
    headers: list[dict[str, str]] = field(default_factory=list)
    payloads: list[dict[str, Any]] = field(default_factory=list)


@contextmanager
def endpoint_gateway(
    routes: Mapping[tuple[str, str], Protocol | None],
) -> Iterator[Gateway]:
    gateway = Gateway()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *args: Any) -> None:
            pass

        def respond(self, status: int, body: bytes = b"", mime: str = "application/json") -> None:
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            gateway.requests.append(("GET", self.path, None))
            if ("GET", self.path) not in routes:
                self.respond(404)
                return
            body = {
                "data": [{"id": model, "owned_by": "fixture"} for model in (MODEL, AUXILIARY_MODEL)]
            }
            self.respond(200, json.dumps(body).encode())

        def do_POST(self) -> None:
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            model = payload["model"]
            gateway.requests.append(("POST", self.path, model))
            gateway.headers.append({key.lower(): value for key, value in self.headers.items()})
            gateway.payloads.append(payload)
            protocol = routes.get(("POST", self.path))
            if protocol is None:
                self.respond(404)
                return
            self.respond(200, _sse(protocol, model), "text/event-stream")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    gateway.origin = f"http://127.0.0.1:{server.server_port}"
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    try:
        yield gateway
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
