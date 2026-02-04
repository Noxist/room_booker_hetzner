import sys
from datetime import datetime
from typing import Optional


class ServerLogger:
    def __init__(self, stream: Optional[object] = None) -> None:
        self._stream = stream or sys.stdout

    def log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._stream.write(f"[{timestamp}] {message}\n")
        self._stream.flush()
