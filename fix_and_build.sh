#!/usr/bin/env bash
set -euo pipefail
export PYTHONUTF8=1

echo "== ComplexEditor: detect Python ≥3.10, build with PyInstaller =="

# ---- Pick Python (as an argument array; no eval) ----
pick_python_array() {
  # 1) Explicit override
  if [[ -n "${PYTHON_EXE:-}" ]]; then
    if "$PYTHON_EXE" -c 'import sys; exit(0 if sys.version_info>=(3,10) else 1)' 2>/dev/null; then
      printf '%s\0' "$PYTHON_EXE"; return 0
    else
      echo "ERROR: PYTHON_EXE is < 3.10" >&2; return 1
    fi
  fi
  # 2) Common Windows installs
  USERNAME_GUESSED="${USERNAME:-$USER}"
  CANDS=(
    "/c/Users/${USERNAME_GUESSED}/AppData/Local/Programs/Python/Python312/python.exe"
    "/c/Users/${USERNAME_GUESSED}/AppData/Local/Programs/Python/Python311/python.exe"
    "/c/Users/${USERNAME_GUESSED}/AppData/Local/Programs/Python/Python310/python.exe"
    "/c/Python312/python.exe" "/c/Python311/python.exe" "/c/Python310/python.exe"
  )
  for exe in "${CANDS[@]}"; do
    if [[ -x "$exe" ]] && "$exe" -c 'import sys; exit(0 if sys.version_info>=(3,10) else 1)' 2>/dev/null; then
      printf '%s\0' "$exe"; return 0
    fi
  done
  # 3) Windows py launcher
  if command -v py >/dev/null 2>&1; then
    for v in 3.12 3.11 3.10; do
      if py -$v -c 'import sys; exit(0 if sys.version_info>=(3,10) else 1)' >/dev/null 2>&1; then
        printf '%s\0%s\0' "py" "-$v"; return 0
      fi
    done
  fi
  # 4) Fallback: python if ≥3.10
  if command -v python >/dev/null 2>&1; then
    if python -c 'import sys; exit(0 if sys.version_info>=(3,10) else 1)'; then
      printf '%s\0' "python"; return 0
    fi
  fi
  return 1
}
mapfile -d '' -t PYBIN_CMD < <(pick_python_array) || { echo "ERROR: Need Python ≥3.10"; exit 1; }
echo "Using interpreter: $("${PYBIN_CMD[@]}" -c 'import sys; print(sys.executable)')"
"${PYBIN_CMD[@]}" -c 'import sys; print("Python version:", sys.version)'

# ---- Create & activate venv ----
"${PYBIN_CMD[@]}" -m venv .venv
# shellcheck disable=SC1091
source .venv/Scripts/activate

# ---- Clean old artifacts ----
rm -rf build dist .pytest_cache || true
rm -f ./*.spec || true

# ---- Ensure src layout & remove shadow package directory if present ----
if [[ ! -d src ]]; then
  echo "ERROR: src/ layout not found."; exit 1
fi
if [[ -d complex_editor && -d src/complex_editor ]]; then
  SHADOW="._shadow_complex_editor_$(date +%s)"
  echo "Moving top-level ./complex_editor → ${SHADOW}"
  mv complex_editor "${SHADOW}"
fi

# ---- Ensure pyproject.toml exists (no fragile in-place edits) ----
if [[ ! -f pyproject.toml ]]; then
  cat > pyproject.toml <<'EOF'
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "complex_editor"
version = "0.0.0"
requires-python = ">=3.10"

[tool.setuptools]
package-dir = {"" = "src"}

[tool.setuptools.packages.find]
where = ["src"]
EOF
  echo "Wrote minimal pyproject.toml with src layout."
else
  echo "Found existing pyproject.toml; not editing in place."
  echo "NOTE: Build will still work because we pass '--paths src' to PyInstaller."
fi

# ---- Tools for Python 3.12 on Windows ----
python -m pip install --upgrade pip wheel setuptools
python -m pip install "pyinstaller>=6.6"      # 3.12 support
python -m pip install "pyodbc>=5.0"           # 3.12 wheels available on Windows

# ---- Install your package (editable) ----
python -m pip install -e .

# ---- Import sanity (verifies 'ui' is visible) ----
echo "== Import sanity =="
PYTHONPATH=src python - <<'PY'
import pkgutil, complex_editor
print("complex_editor file:", complex_editor.__file__)
mods = [m.name for m in pkgutil.iter_modules(complex_editor.__path__)]
print("subpackages:", ",".join(sorted(mods)))
assert "ui" in mods, "ui subpackage not visible at import time"
PY

# ---- Build with PyInstaller ----
echo "== Building =="
pyinstaller -F -n ComplexEditor \
  --paths src \
  --collect-submodules complex_editor \
  --collect-data complex_editor \
  src/complex_editor/__main__.py

echo
echo "== Done. Binary in ./dist/ComplexEditor.exe =="
