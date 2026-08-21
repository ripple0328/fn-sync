#!/bin/sh
set -eu

project_dir=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_dir"

./scripts/sync-plugin-runtime.sh

python3 -m compileall -q src tests omarchy-plugin/scripts omarchy-plugin/tests
python3 -m unittest discover -s tests -v
python3 -m unittest discover -s omarchy-plugin/tests -v

if command -v ruff >/dev/null 2>&1; then
  ruff check --no-cache src tests omarchy-plugin/scripts omarchy-plugin/tests
elif [ "${CI:-}" = "true" ]; then
  echo "ruff is required in CI" >&2
  exit 1
fi

shell_files="
bin/fn-sync
bin/fnsync
scripts/build-packages.sh
scripts/ci.sh
scripts/demo-fn-syncctl
scripts/fn-sync-omarchy-setup
scripts/fnsync-omarchy-setup
scripts/install-omarchy-bundle.sh
scripts/install-omarchy-plugin.sh
scripts/install.sh
scripts/prepare-aur.sh
scripts/release-source.sh
scripts/sync-plugin-runtime.sh
scripts/verify-package.sh
omarchy-plugin/scripts/fn-syncctl
"
if command -v shellcheck >/dev/null 2>&1; then
  # shellcheck disable=SC2086
  shellcheck $shell_files
elif [ "${CI:-}" = "true" ]; then
  echo "shellcheck is required in CI" >&2
  exit 1
fi

qmlformat_bin=$(command -v qmlformat || true)
if [ -z "$qmlformat_bin" ] && [ -x /usr/lib/qt6/bin/qmlformat ]; then
  qmlformat_bin=/usr/lib/qt6/bin/qmlformat
fi
if [ -n "$qmlformat_bin" ]; then
  for qml in omarchy-plugin/BarWidget.qml omarchy-plugin/Panel.qml omarchy-plugin/PanelPageHeader.qml omarchy-plugin/FnSyncIcon.qml; do
    "$qmlformat_bin" "$qml" >/dev/null
  done
elif [ "${CI:-}" = "true" ]; then
  echo "qmlformat is required in CI" >&2
  exit 1
fi

if command -v omarchy >/dev/null 2>&1; then
  omarchy plugin validate omarchy-plugin
elif [ -n "${OMARCHY_PLUGIN_VALIDATOR:-}" ]; then
  bash "$OMARCHY_PLUGIN_VALIDATOR" omarchy-plugin
elif [ "${CI:-}" = "true" ]; then
  echo "an Omarchy plugin validator is required in CI" >&2
  exit 1
fi
