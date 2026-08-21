#!/bin/sh
set -eu

project_dir=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
version=$(tr -d '[:space:]' < "$project_dir/VERSION")
package_path=${1:-}
plugin_archive=${2:-"$project_dir/dist/fn-sync-omarchy-plugin-$version.tar.gz"}

if [ -z "$package_path" ]; then
  package_path=$(find "$project_dir/dist" -maxdepth 1 -type f -name "fn-sync-$version-*.pkg.tar.zst" -print -quit)
fi
if [ -z "$package_path" ] || [ ! -f "$package_path" ]; then
  echo "fn-sync package for $version was not found" >&2
  exit 1
fi
if [ ! -f "$plugin_archive" ]; then
  echo "plugin archive was not found: $plugin_archive" >&2
  exit 1
fi

contents=$(bsdtar -tf "$package_path")
for expected in \
  usr/bin/fn-sync \
  usr/lib/fn-sync/fnsync.py \
  usr/lib/systemd/user/fnsync.service \
  usr/share/applications/fn-sync.desktop \
  usr/share/fn-sync/omarchy-plugin/manifest.json \
  usr/share/fn-sync/omarchy-plugin/BarWidget.qml \
  usr/share/fn-sync/omarchy-plugin/Panel.qml \
  usr/share/fn-sync/omarchy-plugin/PanelPageHeader.qml \
  usr/share/fn-sync/omarchy-plugin/LICENSE \
  usr/share/fn-sync/omarchy-plugin/preview.png \
  usr/share/fn-sync/omarchy-plugin/scripts/fn-syncctl; do
  printf '%s\n' "$contents" | grep -Fxq "$expected" || {
    echo "package is missing $expected" >&2
    exit 1
  }
done
if printf '%s\n' "$contents" | grep -Eq '(__pycache__|\.pyc$)'; then
  echo "package contains Python cache files" >&2
  exit 1
fi

pkginfo=$(bsdtar -xOf "$package_path" .PKGINFO)
printf '%s\n' "$pkginfo" | grep -Fxq "pkgname = fn-sync"
printf '%s\n' "$pkginfo" | grep -Fxq "pkgver = $version-1"

desktop=$(bsdtar -xOf "$package_path" usr/share/applications/fn-sync.desktop)
printf '%s\n' "$desktop" | grep -Fxq 'Name=FN sync'
printf '%s\n' "$desktop" | grep -Fxq 'Name[zh]=飞牛'
printf '%s\n' "$desktop" | grep -Fxq 'Exec=fn-sync ui'

temp_dir=$(mktemp -d /tmp/fn-sync-package-check.XXXXXX)
cleanup() {
  rm -rf -- "$temp_dir"
}
trap cleanup EXIT INT TERM
tar -xzf "$plugin_archive" -C "$temp_dir"
test -f "$temp_dir/manifest.json"
test -f "$temp_dir/LICENSE"
test -f "$temp_dir/preview.png"
test "$(jq -r .version "$temp_dir/manifest.json")" = "$version"
test "$(jq -r .name "$temp_dir/manifest.json")" = "FN sync"
if find "$temp_dir" -type l -print -quit | grep -q .; then
  echo "plugin archive contains a symlink" >&2
  exit 1
fi
if find "$temp_dir" -type f \( -name '*.pyc' -o -path '*/__pycache__/*' \) -print -quit | grep -q .; then
  echo "plugin archive contains Python cache files" >&2
  exit 1
fi

if command -v omarchy >/dev/null 2>&1; then
  omarchy plugin validate "$temp_dir"
fi
if command -v namcap >/dev/null 2>&1; then
  namcap_output=$(namcap "$package_path")
  printf '%s\n' "$namcap_output"
  if printf '%s\n' "$namcap_output" | grep -q ' E:'; then
    echo "namcap reported a package error" >&2
    exit 1
  fi
fi

echo "verified $package_path"
echo "verified $plugin_archive"
