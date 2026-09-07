#!/usr/bin/env bash
# 发布/回滚脚本：换一个 tag 重跑就是回滚，回滚不依赖 CI 是否可用。
#
# 用法：
#   ./scripts/deploy.sh <tag>          # 例如 ./scripts/deploy.sh v1.4.2
#
# 前置条件（一次性，见 #71 服务器准备）：
#   - 当前目录是仓库的 git clone（脚本会在这里 checkout <tag>）
#   - docker + docker compose 插件已安装
#   - gh CLI 已认证（用于从 Release 下载前端产物；GH_TOKEN 环境变量或 gh auth login 均可）
#   - CHATAGENTS_ENV_FILE 指向 clone 目录之外的 .env（默认 /www/chatagents/.env），
#     其中含 POSTGRES_*、ANTHROPIC_API_KEY 等——本脚本只读它，绝不写它
#   - CHATAGENTS_FRONTEND_ROOT 指向前端产物落盘目录（默认 /www/chatagents/frontend）
set -euo pipefail

TAG="${1:?用法: deploy.sh <tag>，例如 deploy.sh v1.4.2}"
REPO="${CHATAGENTS_REPO:-EllisYuan/ChatAgents}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${CHATAGENTS_ENV_FILE:-/www/chatagents/.env}"
FRONTEND_ROOT="${CHATAGENTS_FRONTEND_ROOT:-/www/chatagents/frontend}"

cd "$REPO_DIR"

echo "==> [1/5] 同步仓库到 $TAG（含 compose / nginx include / 本脚本自身）"
git fetch --tags --force
git checkout "$TAG"

# 本脚本随 checkout 一起换版——bash 边读边执行，checkout 会在执行中途
# 改掉自己所在的文件。用 exec 重新拉起换版后的脚本，保证后续步骤跑的是
# $TAG 那一份，而不是内存里残留的旧版本。
if [[ -z "${CHATAGENTS_DEPLOY_REEXECUTED:-}" ]]; then
  export CHATAGENTS_DEPLOY_REEXECUTED=1
  exec "$REPO_DIR/scripts/deploy.sh" "$TAG"
fi

if [[ ! -f "$ENV_FILE" ]]; then
  echo "缺少 $ENV_FILE（应在 clone 目录之外手工准备，见 #71）" >&2
  exit 1
fi

export APP_VERSION="$TAG"
COMPOSE=(docker compose -f compose.yaml -f compose.prod.yaml --env-file "$ENV_FILE")

echo "==> [2/5] 拉取 ghcr.io 镜像 $APP_VERSION"
"${COMPOSE[@]}" pull migrate backend

echo "==> [3/5] 起 postgresql / 跑迁移 / 换后端（迁移失败会让 backend 起不来，失败可辨识）"
"${COMPOSE[@]}" up -d

echo "==> [4/5] 下发前端产物到宿主机磁盘"
dist_dir="$(mktemp -d)"
trap 'rm -rf "$dist_dir"' EXIT

gh release download "$TAG" \
  --repo "$REPO" \
  --pattern 'frontend-dist-*.tar.gz' \
  --dir "$dist_dir" \
  --clobber

archive="$(find "$dist_dir" -maxdepth 1 -name 'frontend-dist-*.tar.gz' -print -quit)"
if [[ -z "$archive" ]]; then
  echo "Release $TAG 下没有找到前端产物（frontend-dist-*.tar.gz）" >&2
  exit 1
fi

release_dir="$FRONTEND_ROOT/$TAG"
rm -rf "$release_dir"
mkdir -p "$release_dir"
tar -xzf "$archive" -C "$release_dir"
ln -sfn "$release_dir" "$FRONTEND_ROOT/current"

echo "==> [5/5] 完成：$TAG 已上线（回滚就是用旧 tag 重跑本脚本）"
