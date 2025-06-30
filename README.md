# Complex‑Editor

**Complex‑Editor** is a Python tool that lets engineers create, edit and export *complex device* definitions for Seica / VIVA ATE systems.

* ⚙️  Build new complexes by combining existing VIVA macros, pins and parameters  
* 📎  View the component datasheet side‑by‑side while you work  
* 🗄️  Store complexes in a searchable SQLite library  
* 📤  Export selected complexes straight into any VIVA program MDB with automatic backup & diff  
* 🧠  Road‑map: AI assistant to extract pin maps and parameters directly from the PDF datasheet

## Quick start (dev mode)

```bash
git clone https://github.com/your‑org/complex‑editor.git
cd complex‑editor
python -m venv .venv && source .venv/bin/activate      # Windows: .\.venv\Scripts\activate
pip install -r requirements.txt
python -m complex_editor.cli --help
```

## Directory layout

```
src/complex_editor/   # application packages
tests/                # pytest unit tests
examples/             # demo MDB & PDF (not committed)
```
