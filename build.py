import os
import sys
from pathlib import Path
import subprocess

APP_NAME = "RoomBooker"
BASE_DIR = Path(__file__).resolve().parent
DIST_DIR = BASE_DIR / "dist"
BUILD_DIR = BASE_DIR / "build"


def main() -> None:
    env = os.environ.copy()
    env.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--name",
        APP_NAME,
        "--onefile",
        "--windowed",
        "--clean",
        "--distpath",
        str(DIST_DIR),
        "--workpath",
        str(BUILD_DIR),
        "--collect-all",
        "playwright",
        "main.py",
    ]

    print("Running:", " ".join(cmd))
    subprocess.check_call(cmd, env=env, cwd=str(BASE_DIR))


if __name__ == "__main__":
    main()
