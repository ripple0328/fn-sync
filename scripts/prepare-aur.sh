#!/bin/sh
set -eu

project_dir=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
version=$(tr -d '[:space:]' < "$project_dir/VERSION")
source_archive=${1:-"$project_dir/dist/fn-sync-$version.tar.gz"}
output_dir=${2:-"$project_dir/dist/aur/fn-sync"}

if [ ! -f "$source_archive" ]; then
  echo "release source archive not found: $source_archive" >&2
  exit 1
fi
if ! command -v makepkg >/dev/null 2>&1; then
  echo "makepkg is required to generate .SRCINFO" >&2
  exit 1
fi

checksum=$(sha256sum "$source_archive" | awk '{print $1}')
mkdir -p "$output_dir"
sed \
  -e "s/^pkgver=.*/pkgver=$version/" \
  -e "s/^sha256sums=.*/sha256sums=('$checksum')/" \
  "$project_dir/packaging/aur/PKGBUILD" > "$output_dir/PKGBUILD"
install -m644 "$project_dir/packaging/arch/fn-sync.install" "$output_dir/fn-sync.install"
(
  cd "$output_dir"
  makepkg --printsrcinfo > .SRCINFO
)

echo "$output_dir"
