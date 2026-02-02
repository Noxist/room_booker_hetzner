from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class Account:
    email: str = ""
    password: str = ""
    active: bool = True
    status: str = "Bereit"


@dataclass
class Job:
    date_mode: str
    date_value: str
    start_time: str
    end_time: str
    rooms: List[str]

    @property
    def label(self) -> str:
        if self.date_mode == "relative":
            return f"Relativ: {self.date_value}"
        return self.date_value

    def to_dict(self) -> Dict[str, object]:
        return {
            "date_mode": self.date_mode,
            "date_value": self.date_value,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "rooms": list(self.rooms),
        }

    @staticmethod
    def from_dict(data: Dict[str, object]) -> "Job":
        return Job(
            date_mode=data.get("date_mode", "single"),
            date_value=data.get("date_value", ""),
            start_time=data.get("start_time", "08:00"),
            end_time=data.get("end_time", "18:00"),
            rooms=list(data.get("rooms", [])),
        )


@dataclass
class Settings:
    accounts: List[Account] = field(default_factory=list)
    simulation: bool = True
    theme: str = "Dark"
