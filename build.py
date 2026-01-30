import os
import sys
from pathlib import Path
import shutil
import subprocess

APP_NAME = "RoomBooker"
BASE_DIR = Path(__file__).resolve().parent
DIST_DIR = BASE_DIR / "dist"
BUILD_DIR = BASE_DIR / "build"
ICON_DIR = BASE_DIR / "assets" / "icons"
INNO_SCRIPT = BASE_DIR / "installer" / "room_booker.iss"


def main() -> None:
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
        "--onedir",
        "--noconsole",
        "--clean",
        "--distpath",
        str(DIST_DIR),
        "--workpath",
        str(BUILD_DIR),
        "--collect-all",
        "playwright",
        "main.py",
    ]
    if icon_path:
        cmd.extend(["--icon", str(icon_path)])

    print("Running:", " ".join(cmd))
    subprocess.check_call(cmd, env=env, cwd=str(BASE_DIR))

    if INNO_SCRIPT.exists():
        iscc = shutil.which("iscc")
        if iscc:
            print("Running Inno Setup:", iscc)
            subprocess.check_call([iscc, str(INNO_SCRIPT)], cwd=str(BASE_DIR))
        else:
            print("Inno Setup (iscc) not found; skipping installer build.")


if __name__ == "__main__":
    main()
