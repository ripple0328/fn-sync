#!/bin/sh
set -eu

project_dir=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
version=$(tr -d '[:space:]' < "$project_dir/VERSION")
ref=${1:-HEAD}
output=${2:-"$project_dir/dist/fn-sync-$version.tar.gz"}
output_dir=$(dirname -- "$output")
prefix="fn-sync-$version"

mkdir -p "$output_dir"
archive_tar=$(mktemp /tmp/fn-sync-release-source.XXXXXX)
archive_gzip=$(mktemp "$output_dir/.fn-sync-release.XXXXXX")
cleanup() {
  rm -f -- "$archive_tar"
  if [ -n "${archive_gzip:-}" ]; then
    rm -f -- "$archive_gzip"
  fi
}
trap cleanup EXIT INT TERM

git -C "$project_dir" archive \
  --format=tar \
  --prefix="$prefix/" \
  --output="$archive_tar" \
  "$ref"
gzip -n -c "$archive_tar" > "$archive_gzip"

test -s "$archive_gzip"
tar -tzf "$archive_gzip" | grep -Fxq "$prefix/VERSION"
archive_version=$(tar -xOzf "$archive_gzip" "$prefix/VERSION" | tr -d '[:space:]')
test "$archive_version" = "$version"

# mktemp intentionally creates a private file. Release archives are public
# inputs to packagers, so normalize the final artifact before another user
# (the unprivileged AUR build account in CI) consumes it.
chmod 0644 "$archive_gzip"
mv "$archive_gzip" "$output"
archive_gzip=

echo "$output"
