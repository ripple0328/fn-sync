#!/bin/sh
set -eu

project_dir=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
version=$(tr -d '[:space:]' < "$project_dir/VERSION")
ref=${1:-HEAD}
output=${2:-"$project_dir/dist/fn-sync-$version.tar.gz"}

mkdir -p "$(dirname -- "$output")"
git -C "$project_dir" archive \
  --format=tar \
  --prefix="fn-sync-$version/" \
  "$ref" | gzip -n > "$output"

echo "$output"
