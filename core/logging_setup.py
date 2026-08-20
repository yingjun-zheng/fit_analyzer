"""日志模块：滚动文件日志 + 控制台 + 内存环形缓冲（供 Web 界面查看）。"""
import logging
import logging.handlers
import threading
import time
from pathlib import Path

_RING = []
_RING_LOCK = threading.Lock()
_RING_MAX = 1000


class RingHandler(logging.Handler):
    def emit(self, record):
        try:
            msg = self.format(record)
            with _RING_LOCK:
                _RING.append((record.created, record.levelname, msg))
                if len(_RING) > _RING_MAX:
                    del _RING[: len(_RING) - _RING_MAX]
        except Exception:
            pass


def get_ring(limit=300):
    with _RING_LOCK:
        return list(reversed(_RING[-limit:]))


def clear_ring():
    with _RING_LOCK:
        _RING.clear()


def setup_logging(data_dir: Path, level=logging.INFO, console=True):
    logs_dir = data_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("fit")
    logger.setLevel(level)
    if logger.handlers:
        return logger
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s", "%Y-%m-%d %H:%M:%S"
    )
    fh = logging.handlers.RotatingFileHandler(
        logs_dir / "fit_analyzer.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    rh = RingHandler()
    rh.setFormatter(logging.Formatter("%(levelname)s | %(message)s"))
    logger.addHandler(rh)
    if console:
        ch = logging.StreamHandler()
        ch.setFormatter(fmt)
        logger.addHandler(ch)
    return logger


def get_logger(name="fit"):
    return logging.getLogger(name)


def mask_secret(value):
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return value[:4] + "****" + value[-2:]
