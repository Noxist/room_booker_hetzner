import random
import time
from datetime import datetime
from pathlib import Path
from typing import Callable


def human_type(page, selector: str, text: str) -> None:
    try:
        page.focus(selector)
        for char in text:
            page.keyboard.type(char, delay=random.randint(20, 60))
    except Exception:
        pass


def human_sleep(min_s: float = 0.5, max_s: float = 1.5) -> None:
    time.sleep(random.uniform(min_s, max_s))


class OutputRedirector:
    def __init__(self, callback: Callable[[str], None]):
        self.callback = callback

    def write(self, text: str) -> None:
        if text and text.strip():
            self.callback(text.strip())

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        return False


class Logger:
    def __init__(self, queue_obj, log_file: Path) -> None:
        self.queue = queue_obj
        self.log_file = log_file

    def log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        full_msg = f"[{timestamp}] {message}"
        print(full_msg)
        try:
            with self.log_file.open("a", encoding="utf-8") as handle:
                handle.write(full_msg + "\n")
        except Exception:
            pass
        self.queue.put(full_msg)
