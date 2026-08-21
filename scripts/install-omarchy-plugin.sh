#!/bin/sh
set -eu

project_dir=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
"$project_dir/scripts/sync-plugin-runtime.sh"
FNSYNC_PLUGIN_SOURCE="$project_dir/omarchy-plugin"
export FNSYNC_PLUGIN_SOURCE
exec "$project_dir/scripts/fn-sync-omarchy-setup" "$@"
