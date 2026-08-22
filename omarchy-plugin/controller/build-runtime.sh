#!/bin/sh
set -eu

plugin_dir=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
architecture=${1:-}
output_dir=${2:-"$plugin_dir/build/runtime"}

case "$architecture" in
  amd64)
    expected_machine=x86_64
    ;;
  arm64)
    expected_machine=aarch64
    ;;
  *)
    echo "usage: build-runtime.sh [amd64|arm64] [output-directory]" >&2
    exit 2
    ;;
esac

machine=$(uname -m)
[ "$machine" = "$expected_machine" ] || {
  echo "cannot build $architecture plugin runtime on $machine" >&2
  exit 1
}

python3 -m PyInstaller \
  --clean \
  --noconfirm \
  --onefile \
  --name "fn-sync-runtime-$architecture" \
  --paths "$plugin_dir/controller" \
  --paths "$plugin_dir/scripts" \
  --distpath "$output_dir" \
  --workpath "$plugin_dir/build/pyinstaller-$architecture" \
  --specpath "$plugin_dir/build" \
  "$plugin_dir/controller/entrypoint.py"

runtime="$output_dir/fn-sync-runtime-$architecture"
chmod 0755 "$runtime"
"$runtime" --version
PATH=/nonexistent "$runtime" plugin-discover >/dev/null
