#!/bin/sh
set -eu

project_dir=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
runtime_dir="$project_dir/omarchy-plugin/runtime"

mkdir -p "$runtime_dir/ui"
install -m 0755 "$project_dir/src/fnsync.py" "$runtime_dir/fnsync.py"
install -m 0644 "$project_dir/ui/app.js" "$runtime_dir/ui/app.js"
install -m 0644 "$project_dir/packaging/fnsync-plugin.service" "$runtime_dir/fnsync.service"
