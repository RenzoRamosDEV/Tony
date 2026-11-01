import os
import threading
from pathlib import Path
from typing import TextIO

from tony.core.config.placeholders import SecretMasker

JOIN_TIMEOUT_S = 2.0


class MaskedStderr:
    """A pipe whose write end is a stdio server's stderr; a thread masks each line into a log.

    The SDK hands the write end's descriptor to the child process, so the masking has to happen
    on the read side: output never reaches the log file unmasked.
    """

    def __init__(self, path: Path, masker: SecretMasker) -> None:
        self.path = path
        self._masker = masker
        self.reader = threading.Thread(target=self._copy, daemon=True)
        self._read_fd = -1
        self._errlog: TextIO | None = None

    def __enter__(self) -> TextIO:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._read_fd, write_fd = os.pipe()
        self._errlog = os.fdopen(write_fd, "w", encoding="utf-8")
        self.reader.start()
        return self._errlog

    def __exit__(self, *exc_info: object) -> None:
        if self._errlog is not None:
            self._errlog.close()
        self.reader.join(JOIN_TIMEOUT_S)

    def _copy(self) -> None:
        with (
            os.fdopen(self._read_fd, encoding="utf-8", errors="replace") as source,
            self.path.open("a", encoding="utf-8") as log,
        ):
            for line in source:
                log.write(self._masker.mask(line))
                log.flush()
