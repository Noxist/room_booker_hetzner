import argparse
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


def build_pyinstaller(*, onedir: bool, debug: bool) -> None:
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
        "--collect-all",
        "roombooker",
        "main.py",
    ]

    system = platform.system().lower()
    if system == "windows":
        if onedir:
            cmd.append("--onedir")
        else:
            cmd.append("--onefile")
        if not debug:
            cmd.append("--noconsole")
    elif system == "darwin":
        cmd.append("--windowed")
        cmd.extend(["--osx-bundle-identifier", "com.roombooker.app"])
    else:
        if onedir:
            cmd.append("--onedir")
        cmd.append("--windowed")

    if icon_path:
        cmd.extend(["--icon", str(icon_path)])

    print("Running:", " ".join(cmd))
    subprocess.check_call(cmd, env=env, cwd=str(BASE_DIR))


def build_windows_installer() -> None:
    installer_script = BASE_DIR / "installer" / "room_booker.iss"
    if not installer_script.exists():
        raise FileNotFoundError(f"Inno Setup script not found: {installer_script}")
    print("Running: iscc", installer_script)
    subprocess.check_call(["iscc", str(installer_script)], cwd=str(installer_script.parent))


def main() -> None:
    parser = argparse.ArgumentParser(description="Build RoomBooker with PyInstaller.")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Build in debug/onedir mode (keeps folder structure).",
    )
    parser.add_argument(
        "--onedir",
        action="store_true",
        help="Force onedir build (alias for --debug mode).",
    )
    parser.add_argument(
        "--installer",
        action="store_true",
        help="Build Windows installer (requires Inno Setup/iscc).",
    )
    args = parser.parse_args()

    version = read_version()
    print(f"Building {APP_NAME} {version}")
    onedir = args.debug or args.onedir or args.installer
    build_pyinstaller(onedir=onedir, debug=args.debug)
    if args.installer:
        system = platform.system().lower()
        if system != "windows":
            raise RuntimeError("--installer is only supported on Windows.")
        build_windows_installer()


if __name__ == "__main__":
    main()
