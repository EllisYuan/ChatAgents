---
paths:
  - "backend/src/chat_agents/tools/**/*.py"
  - "backend/tests/tools/**/*.py"
---

# tools 模块约束

修改本模块前先读 `backend/src/chat_agents/tools/ARCHITECTURE.md`，并只按其中链接继续读取与当前变更相关的 ADR。

完成标准：

1. 新 import 符合文档中的依赖方向，并通过 `lint-imports`。
2. 变更没有绕开文档列出的唯一入口或事实来源。
3. 对应测试覆盖成功路径与本次涉及的失败路径。
4. 若实现改变了职责、入口、依赖或不变量，同一变更更新该 `ARCHITECTURE.md`；纯实现细节不追加文档。
