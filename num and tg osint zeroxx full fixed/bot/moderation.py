"""Process-local moderation, usage, and maintenance state."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class WarningEntry:
    reason: str
    created_at: datetime


@dataclass
class UserProfile:
    user_id: int
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    request_count: int = 0
    command_counts: dict[str, int] | None = None

    def __post_init__(self) -> None:
        if self.command_counts is None:
            self.command_counts = {}


@dataclass
class ModerationEntry:
    action: str
    target: str
    actor: str
    reason: str | None
    created_at: datetime


profiles: dict[int, UserProfile] = {}
warnings: dict[int, list[WarningEntry]] = {}
moderators: set[int] = set()
modlog: list[ModerationEntry] = []
maintenance_enabled = False
maintenance_message = "🛠️ The bot is temporarily under maintenance. Please try again later."
started_at = datetime.now().astimezone()


def observe_user(user: Any) -> UserProfile:
    now = datetime.now().astimezone()
    profile = profiles.get(user.id)
    if profile is None:
        profile = UserProfile(user_id=user.id, first_seen=now, command_counts={})
        profiles[user.id] = profile
    profile.username = user.username or profile.username
    profile.first_name = user.first_name or profile.first_name
    profile.last_name = user.last_name or profile.last_name
    profile.last_seen = now
    return profile


def record_command(user_id: int, command: str) -> None:
    profile = profiles.get(user_id)
    if profile is None:
        return
    profile.request_count += 1
    assert profile.command_counts is not None
    profile.command_counts[command] = profile.command_counts.get(command, 0) + 1


def warning_entries(user_id: int) -> list[WarningEntry]:
    return warnings.setdefault(user_id, [])


def add_modlog(action: str, target: str, actor: str, reason: str | None = None) -> None:
    modlog.append(ModerationEntry(action, target, actor, reason, datetime.now().astimezone()))
    del modlog[:-100]
