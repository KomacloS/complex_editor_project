import os

# Force PyQt6 binding for pytest-qt and runtime environments that have multiple Qt bindings.
os.environ.setdefault("QT_API", "pyqt6")
