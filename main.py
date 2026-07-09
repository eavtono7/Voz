"""
Voz — Dictado por voz con IA local.

Entry point único para el modo GUI (dictado por voz).
"""

from __future__ import annotations

import logging
import sys


def _setup_logging() -> None:
    """Configure structured logging to file."""
    from core import config

    log_file = config.LOG_PATH
    log_file.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    fh = logging.FileHandler(log_file, encoding="utf-8", mode="w")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    for noisy in ("urllib3", "huggingface_hub", "onnxruntime", "pynput", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def main() -> None:
    from core import config as cfg

    cfg.init()

    _setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("Voz starting")

    try:
        from gui.dictation_app import main as gui_main
        gui_main()
    except Exception:
        logger.exception("Unhandled exception – Voz will exit")
        sys.exit(1)


if __name__ == "__main__":
    main()
