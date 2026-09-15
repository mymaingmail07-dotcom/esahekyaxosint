"""Small local recipient store containing only Telegram user IDs."""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)
_RECIPIENTS_PATH = Path(__file__).resolve().parent.parent / "recipients.txt"


def add_recipient(user_id: int) -> None:
    try:
        existing = (
            set(_RECIPIENTS_PATH.read_text(encoding="utf-8").splitlines())
            if _RECIPIENTS_PATH.exists()
            else set()
        )
        value = str(user_id)
        if value not in existing:
            with _RECIPIENTS_PATH.open("a", encoding="utf-8") as recipients_file:
                recipients_file.write(value + "\n")
    except OSError:
        logger.exception("Could not store broadcast recipient")


def get_recipients() -> list[int]:
    try:
        if not _RECIPIENTS_PATH.exists():
            return []
        recipients: list[int] = []
        for line in _RECIPIENTS_PATH.read_text(encoding="utf-8").splitlines():
            try:
                user_id = int(line.strip())
            except ValueError:
                continue
            if user_id > 0:
                recipients.append(user_id)
        return list(dict.fromkeys(recipients))
    except OSError:
        logger.exception("Could not read broadcast recipients")
        return []