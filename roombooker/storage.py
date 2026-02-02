import json
from typing import Dict, List

from roombooker.config import BLUEPRINTS_FILE, ROOMS_FILE, SETTINGS_FILE
from roombooker.models import Account, Job, Settings


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
        data = {
            "accounts": [acc.__dict__ for acc in settings.accounts],
            "simulation": settings.simulation,
            "theme": settings.theme,
        }
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
