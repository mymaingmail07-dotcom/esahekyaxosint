"""In-memory access control and Force Join checks."""

from dataclasses import dataclass
import logging
import re
from urllib.parse import urlsplit

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramNetworkError

from bot import Settings

logger = logging.getLogger(__name__)

_PUBLIC_TELEGRAM_LINK = re.compile(r"^/(?!joinchat/|\+)([A-Za-z0-9_]{5,})/?$")
_USERNAME = re.compile(r"^@?[A-Za-z0-9_]{5,32}$")


@dataclass
class BannedUser:
    user_id: int
    username: str | None = None


class BanStore:
    """Temporary bans for the current process; no persistent storage is used."""

    def __init__(self) -> None:
        self._bans: dict[int, BannedUser] = {}

    def get(self, user_id: int) -> BannedUser | None:
        return self._bans.get(user_id)

    def add(self, user_id: int, username: str | None = None) -> bool:
        if user_id in self._bans:
            return False
        self._bans[user_id] = BannedUser(user_id, username)
        return True

    def remove(self, user_id: int) -> bool:
        return self._bans.pop(user_id, None) is not None

    def all(self) -> list[BannedUser]:
        return list(self._bans.values())

    def find_username(self, username: str) -> BannedUser | None:
        normalized = username.removeprefix("@").casefold()
        return next(
            (entry for entry in self._bans.values() if entry.username and entry.username.casefold() == normalized),
            None,
        )


def parse_user_id(value: str) -> int | None:
    if not value.isdigit() or not value or int(value) <= 0 or len(value) > 15:
        return None
    return int(value)


def normalize_username(value: str) -> str | None:
    if not _USERNAME.fullmatch(value):
        return None
    return value.removeprefix("@").casefold()


def public_username_from_url(url: str) -> str | None:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() not in {"t.me", "telegram.me"}:
        return None
    match = _PUBLIC_TELEGRAM_LINK.fullmatch(parsed.path)
    return match.group(1) if match else None


class ForceJoinService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.urls = settings.force_join_urls

    async def missing_targets(self, bot: Bot, user_id: int) -> list[str] | None:
        """Return missing labels, or None when a target cannot be checked reliably."""
        if not self.settings.force_join_enabled:
            return []
        missing: list[str] = []
        labels = ("Zerox X Chatgc", "Zerox X Osint", "Zerox X Updates")
        for label, url in zip(labels, self.urls, strict=True):
            username = public_username_from_url(url)
            if not username:
                logger.error(
                    "Force Join target %s cannot be checked: %s is not a public t.me username link. "
                    "Telegram Bot API cannot resolve private invite URLs without a chat ID.",
                    label,
                    url or "(missing URL)",
                )
                missing.append(label)
                continue
            try:
                chat = await bot.get_chat(f"@{username}")
                member = await bot.get_chat_member(chat.id, user_id)
            except (TelegramAPIError, TelegramBadRequest, TelegramNetworkError) as exc:
                logger.warning("Could not verify Force Join target %s (@%s): %s", label, username, exc)
                missing.append(label)
                continue
            except Exception:
                logger.exception("Unexpected error while verifying Force Join target %s", label)
                missing.append(label)
                continue
            if member.status in {"left", "kicked"}:
                missing.append(label)
        return missing
