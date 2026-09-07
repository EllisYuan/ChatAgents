#!/bin/sh
# =============================================================================
# block-dangerous.sh
# PreToolUse hook — 在执行前拦截高危 shell 命令。
#
# Claude Code 通过 stdin 以 JSON 形式传入 hook 输入。对于 Bash 工具的
# PreToolUse 事件，JSON 中包含命令字符串。我们读取完整 JSON 并对已知
# 高危命令做模式匹配。这样可以避免依赖 jq（Windows Git Bash 上可能
# 没有 jq）。
#
# 退出码：
#   0  — 命令安全，允许执行
#   2  — 命令被拦截，不执行（stderr 内容会显示给 Claude）
# =============================================================================

# 从 stdin 读取完整 JSON 输入
INPUT=$(cat)

# 转为小写，方便不区分大小写匹配
INPUT_LOWER=$(echo "$INPUT" | tr '[:upper:]' '[:lower:]')

# --- 辅助函数：拦截并输出原因 ---
# 用法: block "拦截原因"
block() {
  echo "{\"hookSpecificOutput\":{\"hookEventName\":\"PreToolUse\",\"permissionDecision\":\"deny\",\"permissionDecisionReason\":\"$1\"}}"
  exit 2
}

# =============================================================================
# 规则匹配 — 按危险程度从高到低排列
# =============================================================================

# 1. 递归强制删除
echo "$INPUT_LOWER" | grep -qE 'rm\s+-rf|rm\s+-fr|rm\s+--recursive\s+-f|rm\s+-f\s+--recursive'
[ $? -eq 0 ] && block "拦截：检测到 rm -rf。该命令会递归永久删除文件。如果确实需要，请在您的终端中手动执行。"

# 2. Git 破坏性重写命令
echo "$INPUT_LOWER" | grep -qE 'git\s+reset\s+--hard|git\s+checkout\s+\.|git\s+restore\s+\.|git\s+clean\s+-f'
[ $? -eq 0 ] && block "拦截：检测到破坏性 git 命令（reset --hard / checkout . / restore . / clean -f）。这些命令会丢弃未提交的工作。如果确实需要，请手动执行。"

# 3. Git 强制推送
echo "$INPUT_LOWER" | grep -qE 'git\s+push\s+.*--force|git\s+push\s+-f'
[ $? -eq 0 ] && block "拦截：检测到 git push --force。强制推送会改写远程历史记录。如果确实需要，请手动执行。"

# 4. SQL DROP 语句（也能匹配管道传入 mysql 或 heredoc 中的情况）
echo "$INPUT_LOWER" | grep -qE 'drop\s+table|drop\s+database|drop\s+schema'
[ $? -eq 0 ] && block "拦截：检测到 SQL DROP 语句。在无备份的情况下删除表或数据库是不可逆的。如果确实需要，请手动执行。"

# 5. Windows 磁盘格式化
echo "$INPUT_LOWER" | grep -qE 'format\s+[a-z]:'
[ $? -eq 0 ] && block "拦截：检测到磁盘格式化命令。此操作不可逆。"

# 6. Docker 数据卷销毁
echo "$INPUT_LOWER" | grep -qE 'docker\s+compose\s+down\s+-v|docker\s+volume\s+rm|docker\s+system\s+prune\s+-a'
[ $? -eq 0 ] && block "拦截：检测到 Docker 数据卷或系统清理命令。这会删除持久化数据。如果确实需要，请手动执行。"

# 7. 写入 .env 文件（密钥保护）
# 匹配重定向到任意目录下的 .env，但不匹配 .env.sample / .env.example。
echo "$INPUT" | grep -qE '>\s*([^[:space:]]*/)?\.env([[:space:]]|$)'
[ $? -eq 0 ] && block "拦截：检测到对 .env 文件的写入操作。.env 可能包含凭据，请编辑 .env.sample 并手动复制。"

# =============================================================================
# 未匹配到任何拦截规则 — 命令安全，允许执行
# =============================================================================
echo "{\"hookSpecificOutput\":{\"hookEventName\":\"PreToolUse\",\"permissionDecision\":\"allow\"}}"
exit 0
