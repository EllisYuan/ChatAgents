#!/usr/bin/env python3
"""生成并校验 README 中由仓库事实派生的区块。"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
PACKAGE_ROOT = ROOT / "backend/src/chat_agents"
ADR_ROOT = ROOT / "docs/adr"

MODULE_ORDER = [
    "conversation",
    "agent",
    "llm",
    "tools",
    "observability",
    "transport",
    "eval_summary",
    "db",
]
MODULE_LABELS = {
    "conversation": "会话 · 消息 · 输入投影",
    "agent": "ReAct Loop · 工具执行器 · 运行配置",
    "llm": "ModelPort · 三协议适配 · 模型发现",
    "tools": "web_search · web_reader",
    "observability": "run/span · Trace · 用量聚合",
    "transport": "AG-UI over SSE 编码",
    "eval_summary": "站点评测展示面",
    "db": "app / obs ORM",
}
ALIASES = {
    "conversation": "conv",
    "agent": "agent",
    "llm": "llm",
    "tools": "tools",
    "observability": "obs",
    "transport": "transport",
    "eval_summary": "evals",
    "db": "db",
}


def marker(name: str, body: str) -> str:
    return f"<!-- generated: {name} -->\n{body.rstrip()}\n<!-- /generated: {name} -->"


def package_dirs() -> list[str]:
    return [name for name in MODULE_ORDER if (PACKAGE_ROOT / name / "__init__.py").is_file()]


def resolve_import(package: tuple[str, ...], node: ast.ImportFrom) -> tuple[str, ...]:
    if node.level == 0:
        return tuple((node.module or "").split("."))
    keep = max(0, len(package) - (node.level - 1))
    return (*package[:keep], *((node.module or "").split(".")))


def import_edges() -> list[tuple[str, str]]:
    modules = set(package_dirs())
    edges: set[tuple[str, str]] = set()
    for source in modules:
        for path in (PACKAGE_ROOT / source).rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            relative = path.relative_to(ROOT / "backend/src").with_suffix("")
            package = tuple(relative.parts[:-1])
            if path.name == "__init__.py":
                package = (*package, relative.parts[-2])
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                targets: list[tuple[str, ...]] = []
                if isinstance(node, ast.ImportFrom):
                    targets.append(resolve_import(package, node))
                elif isinstance(node, ast.Import):
                    targets.extend(tuple(alias.name.split(".")) for alias in node.names)
                for target in targets:
                    if len(target) >= 2 and target[0] == "chat_agents":
                        destination = target[1]
                        if destination in modules and destination != source:
                            edges.add((source, destination))
    return sorted(
        edges,
        key=lambda edge: (MODULE_ORDER.index(edge[0]), MODULE_ORDER.index(edge[1])),
    )


def generate_import_graph() -> str:
    modules = package_dirs()
    lines = ["```mermaid", "graph TD"]
    for module in modules:
        alias = ALIASES[module]
        lines.append(f'    {alias}["{module}/<br/>{MODULE_LABELS[module]}"]')
    lines.append("")
    for source, destination in import_edges():
        lines.append(f"    {ALIASES[source]} --> {ALIASES[destination]}")
    lines.append("```")
    return "\n".join(lines)


def adr_count() -> int:
    return len(list(ADR_ROOT.glob("[0-9][0-9][0-9][0-9]-*.md")))


def generate_tree() -> str:
    modules = package_dirs()
    lines = [
        "```text",
        "ChatAgents/",
        "├── backend/",
        "│   ├── src/chat_agents/",
        "│   │   ├── main.py              # FastAPI 装配 · 三重包装唯一组装处",
    ]
    for index, module in enumerate(modules):
        branch = "└──" if index == len(modules) - 1 else "├──"
        lines.append(f"│   │   {branch} {module + '/':<20} # {MODULE_LABELS[module]}")
    lines.extend(
        [
            "│   ├── alembic/                 # 加性数据库迁移",
            "│   ├── config/endpoints.yaml     # 端点档案",
            "│   └── tests/                    # unit · contract · replay · integration · eval",
            "├── frontend/                     # React 19 · Vite · TanStack Query · Zustand",
            "├── .claude/rules/                # 按路径渐进加载的 Agent 约束",
            f"├── docs/adr/                     # {adr_count()} 份架构决策记录",
            "├── scripts/dev.py               # 跨平台 setup · test · lint · check",
            "├── scripts/check-docs-drift.py  # README 派生内容防腐",
            "├── Makefile                      # Unix 环境的薄封装",
            "├── PROGRESS.md                   # 跨会话执行状态",
            "└── CONTEXT.md                    # 统一语言，只定义术语是什么",
            "```",
        ]
    )
    return "\n".join(lines)


def generate_docs_table() -> str:
    return "\n".join(
        [
            "| 文件 | 内容 |",
            "|---|---|",
            "| [`CLAUDE.md`](./CLAUDE.md) | Agent 入口地图、标准命令与全局不变量 |",
            "| [`CONTEXT.md`](./CONTEXT.md) | 术语表——只定义术语**是什么**，不记录实现方式 |",
            "| [`PROGRESS.md`](./PROGRESS.md) | 跨会话执行状态、后续事项与阻塞 |",
            f"| [`docs/adr/`](./docs/adr/) | {adr_count()} 份架构决策记录，含被否决方案与理由 |",
            "| `backend/src/chat_agents/*/ARCHITECTURE.md` | 与能力模块共置的职责、边界和不变量 |",
            "| [`docs/research/`](./docs/research/) | 选型阶段的调研报告 |",
            "| [`frontend/src/features/trace/SPEC.md`](./frontend/src/features/trace/SPEC.md) | 跨度树的客户端合并规则 |",
        ]
    )


def generated_blocks() -> dict[str, str]:
    return {
        "import-graph": generate_import_graph(),
        "repository-tree": generate_tree(),
        "docs-table": generate_docs_table(),
    }


def replace_or_check(text: str, name: str, expected_body: str, *, fix: bool) -> tuple[str, bool]:
    pattern = re.compile(
        rf"<!-- generated: {re.escape(name)} -->\n.*?\n<!-- /generated: {re.escape(name)} -->",
        re.DOTALL,
    )
    expected = marker(name, expected_body)
    match = pattern.search(text)
    if match is None:
        raise ValueError(f"README 缺少生成区块标记：{name}")
    if match.group(0) == expected:
        return text, False
    if fix:
        return pattern.sub(lambda _: expected, text, count=1), True
    return text, True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fix", action="store_true", help="把派生区块更新为仓库当前事实")
    args = parser.parse_args()

    text = README.read_text(encoding="utf-8")
    drifted: list[str] = []
    for name, body in generated_blocks().items():
        try:
            text, changed = replace_or_check(text, name, body, fix=args.fix)
        except ValueError as exc:
            print(f"文档防腐检查失败：{exc}", file=sys.stderr)
            return 1
        if changed:
            drifted.append(name)

    if args.fix:
        README.write_text(text, encoding="utf-8")
        if drifted:
            print("已更新 README 生成区块：" + ", ".join(drifted))
        return 0
    if drifted:
        print("README 派生内容已腐化：" + ", ".join(drifted), file=sys.stderr)
        print(
            "运行 `uv run --project backend python scripts/check-docs-drift.py --fix` 修复。",
            file=sys.stderr,
        )
        return 1
    print("README 派生内容与仓库事实一致。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
