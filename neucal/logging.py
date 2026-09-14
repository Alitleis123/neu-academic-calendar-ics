"""CLI logging with UTC timestamps and a structured warning collector."""

import contextlib
import logging
import time


class _Warnings(logging.Handler):
    def __init__(self, warnings):
        super().__init__(logging.WARNING)
        self.warnings = warnings

    def emit(self, record):
        self.warnings.append({"level": record.levelname, "logger": record.name,
                              "message": record.getMessage()})


@contextlib.contextmanager
def configured(level, log_file, warnings):
    logger = logging.getLogger()
    old_level = logger.level
    handlers = []
    try:
        handlers.append(logging.StreamHandler())
        if log_file:
            handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
        formatter = logging.Formatter("%(asctime)sZ %(levelname)s %(name)s: %(message)s",
                                      datefmt="%Y-%m-%dT%H:%M:%S")
        formatter.converter = time.gmtime
        for handler in handlers:
            handler.setFormatter(formatter)
            handler.setLevel(level)
        handlers.append(_Warnings(warnings))
        logger.setLevel(min(level, logging.WARNING))
        for handler in handlers:
            logger.addHandler(handler)
        yield
    finally:
        for handler in handlers:
            logger.removeHandler(handler)
            handler.close()
        logger.setLevel(old_level)
