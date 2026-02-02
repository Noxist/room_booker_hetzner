import os
import sys
import threading
from typing import Callable, Optional

from roombooker.config import PLAYWRIGHT_BROWSERS_PATH
from roombooker.utils import OutputRedirector


class PlaywrightInstaller:
    def __init__(self, logger):
        self.logger = logger
        self._install_lock = threading.Lock()

    def is_installed(self) -> bool:
        if not PLAYWRIGHT_BROWSERS_PATH.exists():
            return False
        return any(
            path.name.startswith("chromium")
            for path in PLAYWRIGHT_BROWSERS_PATH.iterdir()
            if path.is_dir()
        )

    def install(self, output_callback: Optional[Callable[[str], None]] = None) -> bool:
        if self._install_lock.locked():
            return False
        self._install_lock.acquire()
        try:
            PLAYWRIGHT_BROWSERS_PATH.mkdir(parents=True, exist_ok=True)
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(PLAYWRIGHT_BROWSERS_PATH)

            orig_stdout, orig_stderr = sys.stdout, sys.stderr
            if output_callback:
                sys.stdout = sys.stderr = OutputRedirector(output_callback)

            old_argv = sys.argv
            sys.argv = ["playwright", "install", "chromium"]
            try:
                from playwright.__main__ import main as playwright_cli

                playwright_cli()
                return True
            except SystemExit as e:
                return e.code == 0
            except Exception as e:
                if output_callback:
                    output_callback(f"Error: {e}")
                return False
            finally:
                sys.stdout, sys.stderr = orig_stdout, orig_stderr
                sys.argv = old_argv
        finally:
            self._install_lock.release()
