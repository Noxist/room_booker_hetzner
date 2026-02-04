import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional

from roombooker.config import BLUEPRINTS_FILE, ROOMS_FILE, SETTINGS_FILE
from roombooker.models import Account, Job, JobRequest, Settings


class SettingsStore:
    @staticmethod
    def load() -> Settings:
        if not SETTINGS_FILE.exists():
            return Settings(accounts=[Account()])
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            accounts = [Account(**acc) for acc in data.get("accounts", [])]
            if not accounts:
                accounts = [Account()]
            return Settings(
                accounts=accounts,
                simulation=data.get("simulation", True),
                theme=data.get("theme", "Dark"),
            )
        except json.JSONDecodeError:
            return Settings(accounts=[Account()])

    @staticmethod
    def save(settings: Settings) -> None:
        data = asdict(settings)
        SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


class RoomStore:
    @staticmethod
    def load() -> Dict[str, str]:
        if ROOMS_FILE.exists():
            try:
                return json.loads(ROOMS_FILE.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    @staticmethod
    def save(room_map: Dict[str, str]) -> None:
        ROOMS_FILE.write_text(json.dumps(room_map, indent=2), encoding="utf-8")


class BlueprintStore:
    @staticmethod
    def load() -> Dict[str, List[Job]]:
        if not BLUEPRINTS_FILE.exists():
            return {}
        try:
            data = json.loads(BLUEPRINTS_FILE.read_text(encoding="utf-8"))
            return {name: [Job.from_dict(j) for j in jobs] for name, jobs in data.items()}
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def save(blueprints: Dict[str, List[Job]]) -> None:
        payload = {name: [job.to_dict() for job in jobs] for name, jobs in blueprints.items()}
        BLUEPRINTS_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def resolve_data_dir() -> Path:
    return Path(os.environ.get("ROOMBOOKER_DATA_DIR", "/app/data"))


def read_json_file(path: Path) -> Optional[object]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def load_accounts(settings_path: Optional[Path] = None) -> List[Account]:
    target = settings_path or (resolve_data_dir() / "settings.json")
    payload = read_json_file(target)
    if not isinstance(payload, dict):
        return []
    accounts = payload.get("accounts", [])
    if not isinstance(accounts, list):
        return []
    return [Account(**acc) for acc in accounts if isinstance(acc, dict)]


def load_jobs(jobs_path: Optional[Path] = None) -> List[JobRequest]:
    target = jobs_path or (resolve_data_dir() / "jobs.json")
    payload = read_json_file(target)
    if not isinstance(payload, list):
        return []
    jobs: List[JobRequest] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        jobs.append(
            JobRequest(
                active=item.get("active", True),
                day=item.get("day", "Montag"),
                start=item.get("start", "08:00"),
                end=item.get("end", "18:00"),
                rooms=list(item.get("rooms", [])),
                summary=item.get("summary"),
            )
        )
    return jobs


def load_rooms(rooms_path: Optional[Path] = None) -> Dict[str, str]:
    target = rooms_path or (resolve_data_dir() / "rooms.json")
    payload = read_json_file(target)
    if not isinstance(payload, dict):
        return {}
    return {str(name): str(value) for name, value in payload.items()}
