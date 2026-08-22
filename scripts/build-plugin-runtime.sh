#!/bin/sh
set -eu

project_dir=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
exec "$project_dir/omarchy-plugin/controller/build-runtime.sh" "$@"
