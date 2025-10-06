#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="ComplexEditor"
DIST_DIR="$PROJECT_ROOT/dist"
BUILD_DIR="$PROJECT_ROOT/build"
SPEC_FILE="$PROJECT_ROOT/${APP_NAME}.spec"
PYTHON_BIN="${PYTHON:-python}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "error: python interpreter '$PYTHON_BIN' not found" >&2
  exit 1
fi

if ! "$PYTHON_BIN" -c "import PyInstaller" >/dev/null 2>&1; then
  echo "PyInstaller not found. Installing into the current environment..." >&2
  "$PYTHON_BIN" -m pip install --upgrade pip
  "$PYTHON_BIN" -m pip install pyinstaller
fi

cd "$PROJECT_ROOT"

rm -rf "$BUILD_DIR" "$DIST_DIR"
rm -f "$SPEC_FILE"

case "${OSTYPE:-}" in
  msys*|cygwin*|win32*)
    DATA_SEP=';'
    EXEC_SUFFIX='.exe'
    ;;
  *)
    DATA_SEP=':'
    EXEC_SUFFIX=''
    ;;
esac

RESOURCE_DATA="src/complex_editor/resources${DATA_SEP}complex_editor/resources"
ASSET_DATA="src/complex_editor/assets${DATA_SEP}complex_editor/assets"

"$PYTHON_BIN" -m PyInstaller \
  --noconfirm \
  --clean \
  --windowed \
  --name "$APP_NAME" \
  --collect-submodules complex_editor \
  --add-data "$RESOURCE_DATA" \
  --add-data "$ASSET_DATA" \
  src/complex_editor/__main__.py

OUTPUT_PATH="$DIST_DIR/$APP_NAME$EXEC_SUFFIX"

echo "Build complete: $OUTPUT_PATH"
