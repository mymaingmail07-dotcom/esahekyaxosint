"""Shared bot configuration and application helpers."""

from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env.local")


@dataclass(frozen=True)
class Settings:
    bot_token: str
    admin_id: int
    number_api_url: str
    tg_api_url: str
    vehicle_api_url: str
    alt_tg_id: int | None = None
    active_hours: int = 24
    num_rate_limit_seconds: int = 10
    force_join_enabled: bool = False
    force_join_urls: tuple[str, str, str] = ("", "", "")

    @classmethod
    def from_env(cls) -> "Settings":
        required = {
            "BOT_TOKEN": os.getenv("BOT_TOKEN", "").strip(),
            "ADMIN_ID": os.getenv("ADMIN_ID", "").strip(),
            "NUMBER_API_URL": os.getenv("NUMBER_API_URL", "").strip(),
            "TG_API_URL": os.getenv("TG_API_URL", "").strip(),
            "VEHICLE_API_URL": os.getenv("VEHICLE_API_URL", "").strip(),
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise RuntimeError("Missing required environment variables: " + ", ".join(missing))
        try:
            admin_id = int(required["ADMIN_ID"])
        except ValueError as exc:
            raise RuntimeError("ADMIN_ID must be an integer") from exc
        alt_tg_id: int | None = None
        alt_tg_id_value = os.getenv("ALT_TG_ID", "").strip()
        if alt_tg_id_value:
            try:
                parsed_alt_tg_id = int(alt_tg_id_value)
                if parsed_alt_tg_id > 0:
                    alt_tg_id = parsed_alt_tg_id
            except ValueError:
                pass
        return cls(
            bot_token=required["BOT_TOKEN"],
            admin_id=admin_id,
            alt_tg_id=alt_tg_id,
            number_api_url=required["NUMBER_API_URL"],
            tg_api_url=required["TG_API_URL"],
            vehicle_api_url=required["VEHICLE_API_URL"],
            active_hours=max(1, int(os.getenv("ACTIVE_USER_HOURS", "24"))),
            num_rate_limit_seconds=max(0, int(os.getenv("NUM_RATE_LIMIT_SECONDS", "10"))),
            force_join_enabled=os.getenv("FORCE_JOIN_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"},
            force_join_urls=tuple(os.getenv(f"FORCE_JOIN_URL_{index}", "").strip() for index in range(1, 4)),
        )


def get_settings() -> Settings:
    return Settings.from_env()
