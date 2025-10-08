#!/usr/bin/env bash
set -euo pipefail
export PYTHONUTF8=1

# Foldered build: libs unpacked, assets copied beside the EXE, NO console window.

# ----- pick Python ≥3.10 (set PYTHON_EXE to force a path) -----
pick_python_array() {
  if [[ -n "${PYTHON_EXE:-}" ]]; then
    if "$PYTHON_EXE" -c 'import sys; exit(0 if sys.version_info>=(3,10) else 1)' 2>/dev/null; then
      printf '%s\0' "$PYTHON_EXE"; return 0
    else
      echo "ERROR: PYTHON_EXE is not Python ≥3.10" >&2; return 1
    fi
  fi
  if command -v py >/dev/null 2>&1; then
    for v in 3.12 3.11 3.10; do
      if py -$v -c 'import sys; exit(0 if sys.version_info>=(3,10) else 1)' >/dev/null 2>&1; then
        printf '%s\0%s\0' "py" "-$v"; return 0
      fi
    done
  fi
  for exe in python3.12 python3.11 python3.10 python; do
    if command -v "$exe" >/dev/null 2>&1 && "$exe" -c 'import sys; exit(0 if sys.version_info>=(3,10) else 1)'; then
      printf '%s\0' "$exe"; return 0
    fi
  done
  return 1
}
mapfile -d '' -t PYBIN < <(pick_python_array) || {
  echo "ERROR: Need Python ≥3.10. Set PYTHON_EXE to your 3.12 path and re-run." >&2
  exit 1
}
echo "Using interpreter: $("${PYBIN[@]}" -c 'import sys; print(sys.executable)')"
"${PYBIN[@]}" -c 'import sys; print("Python version:", sys.version)'

# ----- venv -----
"${PYBIN[@]}" -m venv .venv
# shellcheck disable=SC1091
source .venv/Scripts/activate

# ----- clean -----
rm -rf build dist .pytest_cache || true
rm -f ./*.spec || true

# ----- sanity -----
[[ -d src ]] || { echo "ERROR: src/ layout not found"; exit 1; }
if [[ -d complex_editor && -d src/complex_editor ]]; then
  mv complex_editor "._shadow_complex_editor_$(date +%s)"
fi

# ----- tools -----
python -m pip install --upgrade pip wheel setuptools
python -m pip install --upgrade "pyinstaller>=6.6" "pyodbc>=5.0"

# ----- install your package -----
python -m pip install -e .

# ----- collect external data -----
shopt -s globstar nullglob
declare -a ADD_DATA_ARGS=()
add_data_glob() {
  local pattern="$1"
  for f in $pattern; do
    local rel="${f#src/}"
    local dest_dir; dest_dir="$(dirname "$rel")"
    ADD_DATA_ARGS+=( "--add-data" "$f;$dest_dir" )
  done
}
# Adjust/extend as needed:
add_data_glob "src/complex_editor/**/*.mdb"
add_data_glob "src/complex_editor/**/functions*.*"
add_data_glob "src/complex_editor/**/*.[yY][aA][mM][lL]"
add_data_glob "src/complex_editor/**/*.[jJ][sS][oO][nN]"
add_data_glob "src/complex_editor/**/*.[tT][xX][tT]"
add_data_glob "src/complex_editor/**/*.[iI][nN][iI]"
add_data_glob "src/complex_editor/**/*.[cC][fF][gG]"
add_data_glob "src/complex_editor/**/*.[cC][sS][vV]"

# ----- build (array to avoid quoting bugs) -----
args=(
  -n ComplexEditor
  --onedir
  --noconsole        # hide terminal window (aka --windowed)
  --debug noarchive  # keep pure-Python modules unpacked
  --clean
  --paths src
  --collect-submodules complex_editor
  --collect-data complex_editor
)
args+=( "${ADD_DATA_ARGS[@]}" )
args+=( "src/complex_editor/__main__.py" )

pyinstaller "${args[@]}"

echo
echo "Build complete → ./dist/ComplexEditor/ (no console window)"
