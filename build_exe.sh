#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="ComplexEditor"
DIST_DIR="$PROJECT_ROOT/dist"
FINAL_BUNDLE_DIR="$DIST_DIR/Complex Editor"
FINAL_INTERNAL_DIR="$FINAL_BUNDLE_DIR/internal"
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

# Ensure PyInstaller bundles every Qt-dependent UI module; otherwise the frozen
# app fails to import ``complex_editor.ui`` when launched on Windows.
"$PYTHON_BIN" -m PyInstaller \
  --noconfirm \
  --clean \
  --windowed \
  --onefile \
  --name "$APP_NAME" \
  --collect-submodules complex_editor \
  --collect-all complex_editor.ui \
  --collect-submodules yaml \
  --hidden-import yaml \
  --add-data "$RESOURCE_DATA" \
  --add-data "$ASSET_DATA" \
  src/complex_editor/__main__.py

EXECUTABLE_PATH="$DIST_DIR/$APP_NAME$EXEC_SUFFIX"

if [ ! -f "$EXECUTABLE_PATH" ]; then
  echo "error: expected PyInstaller output '$EXECUTABLE_PATH' was not produced" >&2
  exit 1
fi

rm -rf "$FINAL_BUNDLE_DIR"
mkdir -p "$FINAL_INTERNAL_DIR"

cp "$EXECUTABLE_PATH" "$FINAL_BUNDLE_DIR/$APP_NAME$EXEC_SUFFIX"
rm -f "$EXECUTABLE_PATH"

if [ -d "$PROJECT_ROOT/internal" ]; then
  cp -R "$PROJECT_ROOT/internal"/. "$FINAL_INTERNAL_DIR"/
fi

rm -rf "$BUILD_DIR"
rm -f "$SPEC_FILE"

echo "Build complete: $FINAL_BUNDLE_DIR/$APP_NAME$EXEC_SUFFIX"
echo "Internal payload: $FINAL_INTERNAL_DIR"
