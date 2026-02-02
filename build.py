import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

APP_NAME = "RoomBooker"
BASE_DIR = Path(__file__).resolve().parent
DIST_DIR = BASE_DIR / "dist"
BUILD_DIR = BASE_DIR / "build"
ICON_DIR = BASE_DIR / "assets" / "icons"
INNO_SCRIPT = BASE_DIR / "installer" / "room_booker.iss"
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
        "--onedir",
        "--clean",
        "--distpath",
        str(DIST_DIR),
        "--workpath",
        str(BUILD_DIR),
        "--collect-all",
        "playwright",
        "main.py",
    ]

    if platform.system().lower() == "windows":
        cmd.append("--noconsole")
    else:
        cmd.append("--windowed")

    if icon_path:
        cmd.extend(["--icon", str(icon_path)])

    print("Running:", " ".join(cmd))
    subprocess.check_call(cmd, env=env, cwd=str(BASE_DIR))


def build_inno_setup() -> None:
    if not INNO_SCRIPT.exists():
        return
    iscc = shutil.which("iscc")
    if not iscc:
        print("Inno Setup (iscc) not found; skipping installer build.")
        return
    print("Running Inno Setup:", iscc)
    subprocess.check_call([iscc, str(INNO_SCRIPT)], cwd=str(BASE_DIR))


def build_dmg() -> None:
    app_path = DIST_DIR / f"{APP_NAME}.app"
    if not app_path.exists():
        print("App bundle not found; skipping DMG build.")
        return
    dmg_path = DIST_DIR / f"{APP_NAME}.dmg"
    create_dmg = shutil.which("create-dmg")
    if create_dmg:
        subprocess.check_call(
            [
                create_dmg,
                "--volname",
                APP_NAME,
                "--window-size",
                "800",
                "400",
                "--app-drop-link",
                "600",
                "185",
                str(dmg_path),
                str(app_path),
            ],
            cwd=str(BASE_DIR),
        )
        return
    if shutil.which("hdiutil"):
        subprocess.check_call(
            [
                "hdiutil",
                "create",
                "-volname",
                APP_NAME,
                "-srcfolder",
                str(app_path),
                "-ov",
                "-format",
                "UDZO",
                str(dmg_path),
            ]
        )
        return
    print("Kein DMG-Tool gefunden; überspringe DMG.")


def main() -> None:
    version = read_version()
    print(f"Building {APP_NAME} {version}")
    build_pyinstaller()
    system = platform.system().lower()
    if system == "windows":
        build_inno_setup()
    elif system == "darwin":
        build_dmg()


if __name__ == "__main__":
    main()
