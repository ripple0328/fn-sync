#!/bin/sh
set -eu

project_dir=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
version=$(tr -d '[:space:]' < "$project_dir/VERSION")
package_path=$(find "$project_dir/dist" -maxdepth 1 -type f -name "fn-sync-$version-*.pkg.tar.zst" -print -quit)

if [ -z "$package_path" ]; then
  echo "未找到已构建的系统包，先运行: ./scripts/build-packages.sh" >&2
  exit 1
fi
if ! command -v omarchy >/dev/null 2>&1; then
  echo "该安装器需要 Omarchy。" >&2
  exit 1
fi

omarchy pkg add rclone python gjs gtk4 libsecret libnotify
sudo pacman -U --needed --noconfirm "$package_path"
fn-sync-omarchy-setup --update
