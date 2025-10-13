#!/usr/bin/env bash
set -euo pipefail
export PYTHONUTF8=1

# Foldered build: libs unpacked, assets copied beside the EXE, NO console window.

# ----- pick Python >=3.10 (set PYTHON_EXE to force a path) -----
declare -a PYBIN=()

try_python() {
  local -a candidate=("$@")
  if "${candidate[@]}" -c 'import sys; exit(0 if sys.version_info>=(3,10) else 1)' >/dev/null 2>&1; then
    PYBIN=("${candidate[@]}")
    return 0
  fi
  return 1
}

find_python_in_known_locations() {
  local user_home
  user_home="$(cd ~ && pwd)"
  local have_cygpath=0
  if command -v cygpath >/dev/null 2>&1; then
    have_cygpath=1
  fi
  local -a guesses=(
    "$user_home/AppData/Local/Programs/Python/Python312/python.exe"
    "$user_home/AppData/Local/Programs/Python/Python311/python.exe"
    "$user_home/AppData/Local/Programs/Python/Python310/python.exe"
  )
  if [[ -n "${LOCALAPPDATA:-}" ]]; then
    local base
    if ((have_cygpath)); then
      base="$(cygpath -u "$LOCALAPPDATA")/Programs/Python"
    else
      base="$LOCALAPPDATA/Programs/Python"
    fi
    guesses+=("$base/Python312/python.exe" "$base/Python311/python.exe" "$base/Python310/python.exe")
  fi
  if [[ -n "${PROGRAMFILES:-}" ]]; then
    local pf
    if ((have_cygpath)); then
      pf="$(cygpath -u "$PROGRAMFILES")"
    else
      pf="$PROGRAMFILES"
    fi
    guesses+=("$pf/Python312/python.exe" "$pf/Python311/python.exe" "$pf/Python310/python.exe")
  fi
  # PROGRAMFILES(X86) is awkward to read in bash; fetch via printenv if available.
  local pf86_raw
  pf86_raw="$(printenv 'PROGRAMFILES(X86)' 2>/dev/null || true)"
  if [[ -n "$pf86_raw" ]]; then
    local pf86
    if ((have_cygpath)); then
      pf86="$(cygpath -u "$pf86_raw")"
    else
      pf86="$pf86_raw"
    fi
    guesses+=("$pf86/Python/Python312/python.exe" "$pf86/Python/Python311/python.exe" "$pf86/Python/Python310/python.exe")
  fi
  for path in "${guesses[@]}"; do
    if [[ -x "$path" ]]; then
      if try_python "$path"; then
        return 0
      fi
    fi
  done
  return 1
}

if [[ -n "${PYTHON_EXE:-}" ]]; then
  try_python "$PYTHON_EXE" || {
    echo "ERROR: PYTHON_EXE is not Python >=3.10" >&2
    exit 1
  }
fi

if ((${#PYBIN[@]} == 0)) && command -v py >/dev/null 2>&1; then
  for v in 3.12 3.11 3.10; do
    if try_python py "-$v"; then
      break
    fi
  done
fi

if ((${#PYBIN[@]} == 0)); then
  for exe in python3.12 python3.11 python3.10 python3 python.exe python; do
    if command -v "$exe" >/dev/null 2>&1; then
      # Skip Windows Store stub
      case "$(command -v "$exe")" in
        */Microsoft/WindowsApps/*) continue ;;
      esac
      if try_python "$exe"; then
        break
      fi
    fi
  done
fi

if ((${#PYBIN[@]} == 0)); then
  find_python_in_known_locations || true
fi

if ((${#PYBIN[@]} == 0)); then
  echo "ERROR: Need Python >=3.10. Set PYTHON_EXE to your 3.12 path and re-run." >&2
  exit 1
fi

echo "Using interpreter: $("${PYBIN[@]}" -c 'import sys; print(sys.executable)')"
"${PYBIN[@]}" -c 'import sys; print("Python version:", sys.version)'

# ----- venv -----
"${PYBIN[@]}" -m venv .venv
# shellcheck disable=SC1091
source .venv/Scripts/activate

# ----- clean -----
clean_path() {
  local target="$1"
  if [[ -e "$target" ]]; then
    if ! rm -rf "$target"; then
      cat <<'EOF' >&2
ERROR: Could not remove prior build artefacts.
Close any running ComplexEditor executables (or Windows Explorer windows in the dist folder) and re-run this script.
EOF
      exit 1
    fi
  fi
}
clean_path build
clean_path dist
clean_path .pytest_cache
shopt -s nullglob
for spec in ./*.spec; do
  rm -f "$spec"
done
shopt -u nullglob

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
    local dest_dir
    dest_dir="$(dirname "$rel")"
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
  --noconfirm        # auto-remove previous dist without prompting
  --clean
  --paths src
  --collect-submodules complex_editor
  --collect-data complex_editor
)
args+=( "${ADD_DATA_ARGS[@]}" )
args+=( "src/complex_editor/__main__.py" )

pyinstaller "${args[@]}"

echo
echo "Build complete -> ./dist/ComplexEditor/ (no console window)"
