#!/bin/sh
set -eu

project_dir=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
version=$(tr -d '[:space:]' < "$project_dir/VERSION")
build_root=$(mktemp -d /tmp/fn-sync-package.XXXXXX)
source_root="$build_root/fn-sync-$version"
arch_dir="$project_dir/packaging/arch"
dist_dir="$project_dir/dist"

cleanup() {
  rm -rf "$build_root"
}
trap cleanup EXIT INT TERM

mkdir -p "$source_root" "$dist_dir"
for item in VERSION LICENSE README.md README.zh-CN.md assets bin docs omarchy-plugin scripts src ui; do
  cp -a "$project_dir/$item" "$source_root/$item"
done
mkdir -p "$source_root/packaging"
cp -a "$project_dir/packaging/fnsync.service" "$source_root/packaging/fnsync.service"
cp -a "$project_dir/packaging/fnsync.desktop" "$source_root/packaging/fnsync.desktop"

tar --exclude='*/__pycache__' --exclude='*.pyc' -czf "$arch_dir/fn-sync-$version.tar.gz" -C "$build_root" "fn-sync-$version"
(
  cd "$arch_dir"
  updpkgsums
  makepkg --cleanbuild --clean --force --nodeps --noconfirm
)

package_path=$(find "$arch_dir" -maxdepth 1 -type f -name "fn-sync-$version-*.pkg.tar.zst" -print -quit)
if [ -z "$package_path" ]; then
  echo "未找到构建完成的 pacman 包" >&2
  exit 1
fi
install -m644 "$package_path" "$dist_dir/$(basename "$package_path")"

tar --exclude='*/__pycache__' --exclude='*.pyc' -czf "$dist_dir/fn-sync-omarchy-plugin-$version.tar.gz" -C "$project_dir/omarchy-plugin" .

bundle_root="$build_root/fn-sync-omarchy-bundle-$version"
mkdir -p "$bundle_root/dist" "$bundle_root/scripts"
install -m644 "$project_dir/VERSION" "$bundle_root/VERSION"
install -m644 "$package_path" "$bundle_root/dist/$(basename "$package_path")"
install -m644 "$dist_dir/fn-sync-omarchy-plugin-$version.tar.gz" \
  "$bundle_root/dist/fn-sync-omarchy-plugin-$version.tar.gz"
install -m755 "$project_dir/scripts/install-omarchy-bundle.sh" \
  "$bundle_root/scripts/install-omarchy-bundle.sh"
install -m644 "$project_dir/packaging/BUNDLE-README.md" "$bundle_root/README.md"
tar -czf "$dist_dir/fn-sync-omarchy-bundle-$version.tar.gz" \
  -C "$build_root" "fn-sync-omarchy-bundle-$version"

echo "Built:"
echo "  $dist_dir/$(basename "$package_path")"
echo "  $dist_dir/fn-sync-omarchy-plugin-$version.tar.gz"
echo "  $dist_dir/fn-sync-omarchy-bundle-$version.tar.gz"
