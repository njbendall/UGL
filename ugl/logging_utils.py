from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class TranscriptLogger:
    log_root: Path
    logger: logging.Logger
    _file_handler: logging.FileHandler | None = None

    @classmethod
    def create(cls, log_root: Path) -> "TranscriptLogger":
        logger = logging.getLogger("ugl")
        logger.setLevel(logging.INFO)
        logger.propagate = False
        if not any(isinstance(handler, logging.StreamHandler) for handler in logger.handlers):
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(logging.Formatter("%(message)s"))
            logger.addHandler(console_handler)
        return cls(log_root=log_root, logger=logger)

    def start_new_transcript(self) -> Path:
        if self._file_handler:
            self.logger.removeHandler(self._file_handler)
            self._file_handler.close()
        self.log_root.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = self.log_root / f"GAMLaunch_{timestamp}.txt"
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter("%(message)s"))
        self.logger.addHandler(file_handler)
        self._file_handler = file_handler
        return log_file
