import logging
import logging.config
import sys
from pathlib import Path


class ColorFormatter(logging.Formatter):
    COLORS = {
        'DEBUG': '\033[36m',
        'INFO': '\033[32m',
        'WARNING': '\033[33m',
        'ERROR': '\033[31m',
        'CRITICAL': '\033[31m',
    }
    RESET = '\033[0m'

    def format(self, record: logging.LogRecord) -> str:  # type: ignore[override]
        msg = super().format(record)
        color = self.COLORS.get(record.levelname)
        if color and sys.stderr.isatty():
            msg = f"{color}{msg}{self.RESET}"
        return msg


LOG_DIR = Path.home() / ".complex_editor" / "logs"


def _configure() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    handlers = {
        'file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': str(LOG_DIR / 'complex_editor.log'),
            'maxBytes': 1_000_000,
            'backupCount': 5,
            'encoding': 'utf-8',
            'formatter': 'standard',
        },
    }
    root_handlers = ['file']
    if sys.stderr.isatty():
        handlers['console'] = {
            'class': 'logging.StreamHandler',
            'stream': 'ext://sys.stderr',
            'formatter': 'color',
        }
        root_handlers.append('console')

    logging.config.dictConfig({
        'version': 1,
        'formatters': {
            'standard': {
                'format': '%(asctime)s %(levelname)s %(name)s: %(message)s'
            },
            'color': {
                '()': ColorFormatter,
                'format': '%(levelname)s %(name)s: %(message)s'
            },
        },
        'handlers': handlers,
        'root': {
            'level': 'INFO',
            'handlers': root_handlers,
        },
    })
    for qt_mod in ("PyQt6", "qt"):  # quiet noisy categories
        logging.getLogger(qt_mod).setLevel(logging.WARNING)


_configure()
