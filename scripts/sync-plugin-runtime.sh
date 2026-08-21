#!/bin/sh
set -eu

project_dir=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
runtime_dir="$project_dir/omarchy-plugin/runtime"
binary_dir=${FNSYNC_PLUGIN_RUNTIME_DIR:-}
binary_architectures=${FNSYNC_PLUGIN_RUNTIME_ARCHES:-"amd64 arm64"}

rm -rf -- "$runtime_dir"
mkdir -p "$runtime_dir"
if [ -n "$binary_dir" ]; then
  mkdir -p "$runtime_dir/bin"
  for architecture in $binary_architectures; do
    binary="$binary_dir/fn-sync-runtime-$architecture"
    [ -f "$binary" ] || {
      echo "plugin runtime is missing $binary" >&2
      exit 1
    }
    install -m 0755 "$binary" "$runtime_dir/bin/fn-sync-runtime-$architecture"
  done
else
  # Source checkouts retain a readable Python fallback. The published plugin
  # replaces it with architecture-specific standalone executables in CI.
  install -m 0755 "$project_dir/src/fnsync.py" "$runtime_dir/fnsync.py"
fi
install -m 0644 "$project_dir/packaging/fnsync-plugin.service" "$runtime_dir/fnsync.service"
