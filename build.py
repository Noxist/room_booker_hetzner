import os
import platform
import subprocess
import sys
from pathlib import Path

APP_NAME = "RoomBooker"
BASE_DIR = Path(__file__).resolve().parent
DIST_DIR = BASE_DIR / "dist"
BUILD_DIR = BASE_DIR / "build"
ICON_DIR = BASE_DIR / "assets" / "icons"
VERSION_FILE = BASE_DIR / "version.txt"


def read_version() -> str:
    if VERSION_FILE.exists():
        return VERSION_FILE.read_text(encoding="utf-8").strip()
    return "0.0.0"


def build_pyinstaller() -> None:
    env = os.environ.copy()
    env.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")

    icon_path = None
    for candidate in ("app.ico", "app.png"):
        path = ICON_DIR / candidate
        if path.exists():
            icon_path = path
            break

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--name",
        APP_NAME,
        "--clean",
        "--distpath",
        str(DIST_DIR),
        "--workpath",
        str(BUILD_DIR),
        "--collect-all",
        "playwright",
        "main.py",
    ]

    system = platform.system().lower()
    if system == "windows":
        cmd.append("--onefile")
        cmd.append("--noconsole")
    elif system == "darwin":
        cmd.append("--windowed")
        cmd.extend(["--osx-bundle-identifier", "com.roombooker.app"])
    else:
        cmd.append("--onedir")
        cmd.append("--windowed")

    if icon_path:
        cmd.extend(["--icon", str(icon_path)])

    print("Running:", " ".join(cmd))
    subprocess.check_call(cmd, env=env, cwd=str(BASE_DIR))


def main() -> None:
    version = read_version()
    print(f"Building {APP_NAME} {version}")
    build_pyinstaller()


if __name__ == "__main__":
    main()
