#!/bin/sh
set -eu

project_dir=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
data_home="${XDG_DATA_HOME:-$HOME/.local/share}"
config_home="${XDG_CONFIG_HOME:-$HOME/.config}"

if ! command -v python3 >/dev/null 2>&1; then
  echo "需要 Python 3" >&2
  exit 1
fi

if ! command -v rclone >/dev/null 2>&1; then
  if command -v omarchy >/dev/null 2>&1; then
    echo "未找到 rclone。请先运行: omarchy pkg add rclone" >&2
  else
    echo "未找到 rclone。请使用当前发行版的包管理器安装 rclone 1.66+" >&2
  fi
  exit 1
fi

if ! command -v gjs >/dev/null 2>&1; then
  echo "未找到 GJS/GTK 4，无法安装图形客户端。" >&2
  exit 1
fi

install -Dm755 "$project_dir/src/fnsync.py" "$data_home/fn-sync/fnsync.py"
install -Dm755 "$project_dir/bin/fn-sync" "$HOME/.local/bin/fn-sync"
ln -sfn fn-sync "$HOME/.local/bin/fnsync"
install -Dm644 "$project_dir/ui/app.js" "$data_home/fn-sync/ui/app.js"
install -Dm644 "$project_dir/packaging/fnsync-local.service" "$config_home/systemd/user/fnsync.service"
ln -sfn fnsync.service "$config_home/systemd/user/fn-sync.service"
install -Dm644 "$project_dir/packaging/fnsync.desktop" "$data_home/applications/fn-sync.desktop"
install -Dm644 "$project_dir/assets/fn-sync.png" "$data_home/icons/hicolor/192x192/apps/fn-sync.png"

systemctl --user daemon-reload
systemctl --user enable --now fnsync.service

echo "fn-sync 已安装。运行 fn-sync ui 打开客户端。"
