"""UI package providing lazy access to heavy Qt modules."""

__all__ = ["MainWindow", "run_gui", "NewComplexWizard"]


def __getattr__(name):  # pragma: no cover - simple lazy loader
    if name in {"MainWindow", "run_gui"}:
        from .main_window import MainWindow, run_gui

        return {"MainWindow": MainWindow, "run_gui": run_gui}[name]
    if name == "NewComplexWizard":
        from .new_complex_wizard import NewComplexWizard

        return NewComplexWizard
    raise AttributeError(name)
