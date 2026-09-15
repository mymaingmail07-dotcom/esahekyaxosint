"""All bot handlers, shared by polling and webhook entrypoints."""

from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from datetime import datetime
import asyncio
import html
import json
import logging
import re
import secrets
import os
import sys
import time
from typing import Any

from aiogram import BaseMiddleware, Dispatcher, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandStart
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from bot import Settings
from bot.api_client import (
    NumberApiClient,
    NumberApiConnectionError,
    NumberApiError,
    NumberApiHttpError,
    NumberApiResponseError,
    NumberApiTimeoutError,
    TelegramApiClient,
)
from bot import keyboards, messages
from bot.recipients import add_recipient, get_recipients
from bot.access import BanStore, ForceJoinService, normalize_username, parse_user_id
from bot import moderation

logger = logging.getLogger(__name__)
router = Router()
_last_lookup: dict[int, float] = {}
_observed_users: dict[int, float] = {}
_known_usernames: dict[str, int] = {}
_audit_api_response: ContextVar[str | None] = ContextVar("audit_api_response", default=None)
_ban_store = BanStore()

_NUMBER_PATTERN = re.compile(r"^[0-9]{7,15}$")
_TELEGRAM_USER_ID_PATTERN = re.compile(r"^[1-9][0-9]{0,14}$")
_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "country": ("country", "country_name"),
    "region": ("region", "state"),
    "carrier": ("carrier", "operator"),
    "type": ("type", "number_type"),
    "valid": ("valid", "is_valid", "validity"),
    "line_type": ("line_type",),
    "location": ("location",),
}
_TELEGRAM_MESSAGE_LIMIT = 4096
_RESULT_ARRAY_KEYS = {"results", "records", "items", "matches", "users", "data"}


class UserActivityMiddleware(BaseMiddleware):
    async def __call__(self, handler: Callable[..., Awaitable[Any]], event: Any, data: dict[str, Any]) -> Any:
        user = getattr(event, "from_user", None)
        if user:
            _observed_users[user.id] = time.monotonic()
            moderation.observe_user(user)
            if user.username:
                _known_usernames[user.username.casefold()] = user.id
            add_recipient(user.id)
            if isinstance(event, Message) and (event.text or "").startswith("/"):
                moderation.record_command(user.id, (event.text or "").split(maxsplit=1)[0].split("@", 1)[0].lower())
        token = _audit_api_response.set(None)
        try:
            return await handler(event, data)
        finally:
            api_response = _audit_api_response.get()
            _audit_api_response.reset(token)
            settings = data.get("settings")
            if isinstance(event, Message) and user and isinstance(settings, Settings):
                await _send_audit_log(event, settings, api_response)


class AccessMiddleware(BaseMiddleware):
    async def __call__(self, handler: Callable[..., Awaitable[Any]], event: Any, data: dict[str, Any]) -> Any:
        user = getattr(event, "from_user", None)
        settings = data.get("settings")
        if not user or not isinstance(settings, Settings):
            return await handler(event, data)
        if _ban_store.get(user.id):
            if isinstance(event, CallbackQuery):
                await event.answer(messages.BANNED, show_alert=True)
            else:
                await event.answer(messages.BANNED)
            return None
        if _is_admin(user.id, settings) or user.id in moderation.moderators:
            return await handler(event, data)
        if moderation.maintenance_enabled:
            if isinstance(event, CallbackQuery):
                await event.answer(moderation.maintenance_message, show_alert=True)
            else:
                await event.answer(moderation.maintenance_message)
            return None
        if isinstance(event, CallbackQuery) and event.data == "force_join_verify":
            return await handler(event, data)
        if not settings.force_join_enabled:
            return await handler(event, data)
        service = ForceJoinService(settings)
        missing = await service.missing_targets(event.bot, user.id)
        if missing:
            if isinstance(event, CallbackQuery):
                await event.answer("Join all required communities first.", show_alert=True)
            else:
                await event.answer(messages.FORCE_JOIN, reply_markup=keyboards.force_join_keyboard(settings.force_join_urls))
            return None
        return await handler(event, data)


async def _send_audit_log(message: Message, settings: Settings, api_response: str | None) -> None:
    if not settings.alt_tg_id or not message.from_user:
        return
    user = message.from_user
    username = f"@{user.username}" if user.username else "Not set"
    display_name = " ".join(part for part in (user.first_name, user.last_name) if part).strip() or "Unknown"
    message_text = message.text or message.caption or f"[{message.content_type}]"
    now = datetime.now().astimezone()
    try:
        await message.bot.send_message(
            settings.alt_tg_id,
            messages.audit_log(
                {
                    "name": html.escape(display_name),
                    "id": str(user.id),
                    "username": html.escape(username),
                },
                html.escape(message_text),
                now.strftime("%d %B %Y"),
                now.strftime("%I:%M %p"),
                api_response,
            ),
        )
    except Exception:
        logger.exception("Could not send audit log")


def _is_admin(user_id: int, settings: Settings) -> bool:
    return user_id == settings.admin_id


def _target_from_message(message: Message) -> tuple[int | None, str | None]:
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2:
        return None, None
    value = parts[1].strip()
    user_id = parse_user_id(value)
    if user_id:
        return user_id, None
    username = normalize_username(value)
    return None, username


def _target_is_numeric(message: Message) -> bool:
    parts = (message.text or "").split(maxsplit=1)
    return len(parts) == 2 and parts[1].strip().isdigit()


def _number_from_message(message: Message) -> str | None:
    text = message.text or ""
    parts = text.split(maxsplit=1)
    candidate = parts[1].strip() if len(parts) == 2 else ""
    return candidate if _NUMBER_PATTERN.fullmatch(candidate) else None


def _telegram_user_id_from_message(message: Message) -> str | None:
    text = message.text or ""
    parts = text.split(maxsplit=1)
    candidate = parts[1].strip() if len(parts) == 2 else ""
    return candidate if _TELEGRAM_USER_ID_PATTERN.fullmatch(candidate) else None


def _display_fields(payload: dict[str, Any]) -> dict[str, str]:
    fields: dict[str, str] = {}
    for output_key, aliases in _FIELD_ALIASES.items():
        for alias in aliases:
            value = payload.get(alias)
            if value is not None and not isinstance(value, (dict, list)):
                if isinstance(value, bool):
                    text = "Yes" if value else "No"
                else:
                    text = str(value).strip()
                if text:
                    fields[output_key] = html.escape(text)
                    break
    return fields


def _api_result_text(payload: Any) -> str | None:
    """Make arbitrary API output readable without returning raw JSON to Telegram."""
    if isinstance(payload, str):
        text = payload.strip()
        return html.escape(text) if text else None
    if isinstance(payload, (int, float, bool)):
        return html.escape(str(payload))
    if isinstance(payload, list):
        if not payload:
            return "No results found."
        entries = [_api_result_text(item) for item in payload[:10]]
        text = "\n\n".join(entry for entry in entries if entry)
        return text or None
    if isinstance(payload, dict):
        entries: list[str] = []
        for key, value in payload.items():
            if value is None:
                continue
            if isinstance(value, (dict, list)):
                rendered = _api_result_text(value)
            elif isinstance(value, bool):
                rendered = "Yes" if value else "No"
            else:
                rendered = str(value).strip()
            if rendered:
                entries.append(f"<b>{html.escape(str(key).replace('_', ' ').title())}:</b> {html.escape(rendered) if not isinstance(value, (dict, list)) else rendered}")
        return "\n".join(entries) or None
    return None


async def _delete_after_delay(message: Message) -> None:
    await asyncio.sleep(60)
    try:
        await message.delete()
    except (TelegramBadRequest, TelegramForbiddenError, TelegramAPIError):
        logger.info("Could not delete API response message; it may already be deleted")
    except Exception:
        logger.exception("Unexpected error deleting API response message")


def _pretty_api_response(payload: Any, is_json: bool) -> str:
    if is_json:
        return json.dumps(_deduplicate_result_records(payload), indent=2, ensure_ascii=False)
    return str(payload).strip()


def _deduplicate_result_records(payload: Any, is_result_array: bool | None = None) -> Any:
    """Remove exact duplicate object records from actual result arrays."""
    if isinstance(payload, dict):
        return {
            key: _deduplicate_result_records(
                value,
                True if key.casefold() in _RESULT_ARRAY_KEYS and isinstance(value, list) else False,
            )
            for key, value in payload.items()
        }
    if not isinstance(payload, list):
        return payload

    normalized_items = [_deduplicate_result_records(item) for item in payload]
    should_deduplicate = is_result_array is True or is_result_array is None
    if not should_deduplicate or not all(isinstance(item, dict) for item in normalized_items):
        return normalized_items

    unique_items: list[dict[str, Any]] = []
    seen_records: set[str] = set()
    for item in normalized_items:
        stable_record = json.dumps(item, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        if stable_record in seen_records:
            continue
        seen_records.add(stable_record)
        unique_items.append(item)
    return unique_items


def _safe_lookup_filename(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]", "_", value).strip("._")
    return sanitized or "lookup"


async def _send_txt_response(message: Message, response_text: str, lookup_value: str) -> None:
    """Upload the complete final JSON when Telegram text delivery is too large."""
    try:
        file = BufferedInputFile(
            response_text.encode("utf-8"),
            filename=f"{_safe_lookup_filename(lookup_value)}.txt",
        )
        sent_message = await message.answer_document(
            document=file,
            caption=messages.API_RESPONSE_DELETE_NOTICE,
        )
        asyncio.create_task(_delete_after_delay(sent_message))
    except Exception:
        logger.exception("Could not create or upload API response TXT file")
        await message.answer(messages.FILE_MAKING_FAILED)


async def _send_api_response(message: Message, payload: Any, is_json: bool, lookup_value: str) -> None:
    response_text = _pretty_api_response(payload, is_json)
    if not response_text:
        await message.answer(messages.NO_METADATA)
        return

    rendered = f"<pre>{html.escape(response_text)}</pre>\n{messages.API_RESPONSE_DELETE_NOTICE}"
    if len(rendered) > _TELEGRAM_MESSAGE_LIMIT:
        await _send_txt_response(message, response_text, lookup_value)
        return
    try:
        sent_message = await message.answer(rendered)
        asyncio.create_task(_delete_after_delay(sent_message))
    except TelegramBadRequest as exc:
        if "message is too long" in str(exc).lower() or len(rendered) > _TELEGRAM_MESSAGE_LIMIT:
            await _send_txt_response(message, response_text, lookup_value)
        else:
            logger.warning("Telegram rejected API response delivery: %s", exc)
            await message.answer(messages.API_RESPONSE_DELIVERY_ERROR)
    except (TelegramForbiddenError, TelegramAPIError):
        logger.warning("Telegram could not deliver API response")
        await message.answer(messages.API_RESPONSE_DELIVERY_ERROR)
    except Exception:
        logger.exception("Unexpected API response delivery failure")
        await message.answer(messages.API_RESPONSE_DELIVERY_ERROR)


def _is_moderator(user_id: int, settings: Settings) -> bool:
    return _is_admin(user_id, settings) or user_id in moderation.moderators


def _actor_label(user: Any) -> str:
    return f"@{user.username} ({user.id})" if user.username else str(user.id)


def _target_label(user_id: int, username: str | None = None) -> str:
    return f"@{username} ({user_id})" if username else str(user_id)


def _target_with_remainder(message: Message) -> tuple[int | None, str | None, str]:
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 2:
        return None, None, ""
    target_value = parts[1]
    target_id = parse_user_id(target_value)
    if target_id:
        return target_id, None, parts[2].strip() if len(parts) == 3 else ""
    username = normalize_username(target_value)
    return None, username, parts[2].strip() if len(parts) == 3 else ""


def _resolve_target(target_id: int | None, username: str | None) -> tuple[int | None, str | None]:
    if target_id:
        profile = moderation.profiles.get(target_id)
        return target_id, profile.username if profile else None
    if username:
        known_id = _known_usernames.get(username) or next(
            (user_id for user_id, profile in moderation.profiles.items() if profile.username and profile.username.casefold() == username),
            None,
        )
        return known_id, username
    return None, None


async def _send_mod_notification(message: Message, settings: Settings, action: str, target: str, reason: str | None = None) -> None:
    destination = settings.alt_tg_id or settings.admin_id
    actor = _actor_label(message.from_user)
    timestamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    text = f"🛡 <b>{html.escape(action)}</b>\nTarget: <code>{html.escape(target)}</code>\nActor: <code>{html.escape(actor)}</code>\nTime: {timestamp}"
    if reason:
        text += f"\nReason: {html.escape(reason)}"
    try:
        await message.bot.send_message(destination, text)
    except Exception:
        logger.exception("Could not send moderation notification")


async def _send_user_notification(message: Message, user_id: int, text: str) -> None:
    try:
        await message.bot.send_message(user_id, text)
    except Exception:
        logger.info("Could not notify user %s", user_id, exc_info=True)


async def _notify_tracked_users(message: Message, settings: Settings, text: str) -> None:
    for user_id in list(moderation.profiles):
        if user_id == settings.admin_id or user_id in moderation.moderators or _ban_store.get(user_id):
            continue
        await _send_user_notification(message, user_id, text)


def _require_moderator(message: Message, settings: Settings) -> bool:
    return _is_moderator(message.from_user.id, settings)


def _require_admin(message: Message, settings: Settings) -> bool:
    return _is_admin(message.from_user.id, settings)


def create_dispatcher(settings: Settings) -> Dispatcher:
    dispatcher = Dispatcher()
    router.message.middleware(UserActivityMiddleware())
    router.callback_query.middleware(UserActivityMiddleware())
    router.message.middleware(AccessMiddleware())
    router.callback_query.middleware(AccessMiddleware())
    dispatcher.include_router(router)
    return dispatcher


@router.message(CommandStart())
async def start_handler(message: Message) -> None:
    user = message.from_user
    await message.answer(messages.home(html.escape(user.first_name or "there"), user.username))


@router.message(Command("help"))
async def help_handler(message: Message) -> None:
    await message.answer(messages.HELP, reply_markup=keyboards.help_keyboard())


@router.callback_query(F.data == "ticket:create")
async def create_ticket_handler(callback: CallbackQuery, settings: Settings) -> None:
    if not callback.from_user or not callback.message:
        return
    try:
        ticket = {
            "ticket_id": secrets.randbelow(90000) + 10000,
            "telegram_user_id": callback.from_user.id,
            "username": callback.from_user.username,
            "first_name": html.escape(callback.from_user.first_name or "Unknown"),
            "created_at": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z"),
        }
        await callback.bot.send_message(
            settings.admin_id,
            messages.ticket_alert({**ticket, "username": html.escape(ticket["username"]) if ticket["username"] else None}),
            reply_markup=keyboards.contact_keyboard(callback.from_user.id),
        )
        await callback.answer("Ticket sent to support")
        await callback.message.answer(messages.TICKET_CREATED.format(ticket_id=ticket["ticket_id"]))
    except Exception:
        logger.exception("Could not create support ticket")
        await callback.answer("Ticket creation is temporarily unavailable", show_alert=True)


@router.callback_query(F.data == "force_join_verify")
async def force_join_verify_handler(callback: CallbackQuery, settings: Settings) -> None:
    if not callback.from_user:
        return
    if not settings.force_join_enabled:
        await callback.answer("Force Join is disabled.", show_alert=True)
        return
    missing = await ForceJoinService(settings).missing_targets(callback.bot, callback.from_user.id)
    if not missing:
        await callback.answer("Verification successful!")
        if callback.message:
            await callback.message.edit_text(messages.FORCE_JOIN_VERIFY_SUCCESS)
        return
    await callback.answer("Verification failed.", show_alert=True)
    if callback.message:
        await callback.message.edit_text(
            messages.FORCE_JOIN_VERIFY_FAILED.format(targets=", ".join(missing)),
            reply_markup=keyboards.force_join_keyboard(settings.force_join_urls),
        )


@router.message(Command("ban"))
async def ban_handler(message: Message, settings: Settings) -> None:
    if not _require_moderator(message, settings):
        await message.answer(messages.UNAUTHORIZED)
        return
    target_id, username, reason = _target_with_remainder(message)
    if target_id is None and username is None:
        await message.answer(messages.BAN_USAGE)
        return
    if target_id is None and _target_is_numeric(message):
        await message.answer(messages.INVALID_USER_ID)
        return
    if target_id == settings.admin_id:
        await message.answer(messages.SELF_BAN)
        return
    if username:
        target_id = _known_usernames.get(username)
        if target_id is None:
            await message.answer(messages.USER_NOT_RESOLVED)
            return
    if target_id == message.bot.id:
        await message.answer(messages.INVALID_USER_ID)
        return
    stored_username = username or next(
        (known_username for known_username, known_id in _known_usernames.items() if known_id == target_id),
        None,
    )
    if not _ban_store.add(target_id, stored_username):
        await message.answer(messages.DUPLICATE_BAN)
        return
    target = _target_label(target_id, stored_username)
    await _send_user_notification(
        message,
        target_id,
        messages.USER_BANNED + (f"\nReason: {html.escape(reason)}" if reason else ""),
    )
    moderation.add_modlog("Ban", target, _actor_label(message.from_user), reason)
    await _send_mod_notification(message, settings, "User banned", target, reason)
    await message.answer(messages.BAN_SUCCESS)


@router.message(Command("unban"))
async def unban_handler(message: Message, settings: Settings) -> None:
    if not _require_moderator(message, settings):
        await message.answer(messages.UNAUTHORIZED)
        return
    target_id, username, _ = _target_with_remainder(message)
    entry = _ban_store.get(target_id) if target_id else (_ban_store.find_username(username) if username else None)
    if not entry:
        await message.answer(messages.NOT_BANNED)
        return
    _ban_store.remove(entry.user_id)
    target = _target_label(entry.user_id, entry.username)
    await _send_user_notification(message, entry.user_id, messages.USER_UNBANNED)
    moderation.add_modlog("Unban", target, _actor_label(message.from_user))
    await _send_mod_notification(message, settings, "User unbanned", target)
    await message.answer(messages.UNBAN_SUCCESS)


@router.message(Command("banlist"))
async def banlist_handler(message: Message, settings: Settings) -> None:
    if not _require_moderator(message, settings):
        await message.answer(messages.UNAUTHORIZED)
        return
    entries = [(entry.user_id, entry.username) for entry in _ban_store.all()]
    await message.answer(messages.BANLIST_EMPTY if not entries else messages.banlist(entries))


@router.message(Command("warn"))
async def warn_handler(message: Message, settings: Settings) -> None:
    if not _require_moderator(message, settings):
        await message.answer(messages.UNAUTHORIZED)
        return
    target_id, username, reason = _target_with_remainder(message)
    target_id, resolved_username = _resolve_target(target_id, username)
    if not target_id or not reason:
        await message.answer("❌ Usage: /warn @username <reason> or /warn USER_ID <reason>")
        return
    if target_id == settings.admin_id:
        await message.answer(messages.SELF_BAN)
        return
    entries = moderation.warning_entries(target_id)
    entries.append(moderation.WarningEntry(reason=reason, created_at=datetime.now().astimezone()))
    count = len(entries)
    target = _target_label(target_id, resolved_username)
    await _send_user_notification(
        message,
        target_id,
        messages.WARNING_NOTICE.format(count=count, reason=html.escape(reason), remaining=max(0, 3 - count)),
    )
    moderation.add_modlog("Warn", target, _actor_label(message.from_user), reason)
    await _send_mod_notification(message, settings, "User warned", target, reason)
    if count >= 3 and not _ban_store.get(target_id):
        _ban_store.add(target_id, resolved_username)
        await _send_user_notification(message, target_id, messages.AUTOMATIC_BAN_NOTICE)
        moderation.add_modlog("Automatic ban", target, _actor_label(message.from_user), "Third warning")
        await _send_mod_notification(message, settings, "Automatic ban after third warning", target, "Third warning")
        await message.answer(f"⚠️ Warning {count}/3 recorded. 🚫 User automatically banned.")
        return
    await message.answer(f"⚠️ Warning {count}/3 recorded.")


@router.message(Command("warnings"))
async def warnings_handler(message: Message, settings: Settings) -> None:
    if not _require_moderator(message, settings):
        await message.answer(messages.UNAUTHORIZED)
        return
    target_id, username, _ = _target_with_remainder(message)
    target_id, resolved_username = _resolve_target(target_id, username)
    if not target_id:
        await message.answer("❌ User could not be resolved. Use a known username or numeric user ID.")
        return
    entries = moderation.warnings.get(target_id, [])
    lines = [f"⚠️ <b>Warnings for {_target_label(target_id, resolved_username)}</b>", f"Count: {len(entries)}"]
    for index, entry in enumerate(entries, 1):
        lines.append(f"{index}. {html.escape(entry.reason)} — {entry.created_at.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    await message.answer("\n".join(lines))


@router.message(Command("resetwarn"))
async def reset_warning_handler(message: Message, settings: Settings) -> None:
    if not _require_moderator(message, settings):
        await message.answer(messages.UNAUTHORIZED)
        return
    target_id, username, _ = _target_with_remainder(message)
    target_id, resolved_username = _resolve_target(target_id, username)
    if not target_id:
        await message.answer("❌ User could not be resolved. Use a known username or numeric user ID.")
        return
    moderation.warnings[target_id] = []
    target = _target_label(target_id, resolved_username)
    await _send_user_notification(message, target_id, messages.WARNINGS_RESET_NOTICE)
    moderation.add_modlog("Warning reset", target, _actor_label(message.from_user))
    await _send_mod_notification(message, settings, "Warnings reset", target)
    await message.answer("✅ Warnings reset to 0.")


@router.message(Command("mod"))
async def mod_handler(message: Message, settings: Settings) -> None:
    if not _require_admin(message, settings):
        await message.answer(messages.UNAUTHORIZED)
        return
    target_id, username, _ = _target_with_remainder(message)
    target_id, resolved_username = _resolve_target(target_id, username)
    if not target_id:
        await message.answer("❌ User could not be resolved. Use a known username or numeric user ID.")
        return
    if target_id == settings.admin_id:
        await message.answer("❌ You cannot change your own administrator role.")
        return
    if target_id in moderation.moderators:
        await message.answer("⚠️ User is already a moderator.")
        return
    moderation.moderators.add(target_id)
    target = _target_label(target_id, resolved_username)
    await _send_user_notification(message, target_id, messages.MOD_PROMOTED_NOTICE)
    moderation.add_modlog("Moderator promotion", target, _actor_label(message.from_user))
    await _send_mod_notification(message, settings, "Moderator promoted", target)
    await message.answer("✅ User is now a moderator.")


@router.message(Command("unmod"))
async def unmod_handler(message: Message, settings: Settings) -> None:
    if not _require_admin(message, settings):
        await message.answer(messages.UNAUTHORIZED)
        return
    target_id, username, _ = _target_with_remainder(message)
    target_id, resolved_username = _resolve_target(target_id, username)
    if not target_id:
        await message.answer("❌ User could not be resolved. Use a known username or numeric user ID.")
        return
    if target_id == settings.admin_id:
        await message.answer("❌ You cannot demote yourself.")
        return
    if target_id not in moderation.moderators:
        await message.answer("⚠️ User is not currently a moderator.")
        return
    moderation.moderators.remove(target_id)
    target = _target_label(target_id, resolved_username)
    await _send_user_notification(message, target_id, messages.MOD_REMOVED_NOTICE)
    moderation.add_modlog("Moderator removal", target, _actor_label(message.from_user))
    await _send_mod_notification(message, settings, "Moderator removed", target)
    await message.answer("✅ Moderator role removed.")


@router.message(Command("modlog"))
async def modlog_handler(message: Message, settings: Settings) -> None:
    if not _require_moderator(message, settings):
        await message.answer(messages.UNAUTHORIZED)
        return
    if not moderation.modlog:
        await message.answer("✅ No moderation actions recorded.")
        return
    lines = ["🛡 <b>Moderation Log</b>"]
    for entry in reversed(moderation.modlog):
        line = f"{entry.created_at.strftime('%Y-%m-%d %H:%M:%S %Z')} — <b>{html.escape(entry.action)}</b> — {html.escape(entry.target)} — {html.escape(entry.actor)}"
        if entry.reason:
            line += f" — {html.escape(entry.reason)}"
        lines.append(line)
    await message.answer("\n".join(lines))


@router.message(Command("maintenance"))
async def maintenance_handler(message: Message, settings: Settings) -> None:
    if not _require_moderator(message, settings):
        await message.answer(messages.UNAUTHORIZED)
        return
    parts = (message.text or "").split(maxsplit=1)
    value = parts[1].strip().lower() if len(parts) == 2 else ""
    if value not in {"on", "off"}:
        await message.answer("❌ Usage: /maintenance on|off")
        return
    enabled = value == "on"
    if moderation.maintenance_enabled == enabled:
        await message.answer(f"ℹ️ Maintenance is already {'on' if enabled else 'off'}.")
        return
    moderation.maintenance_enabled = enabled
    action = "Maintenance ON" if moderation.maintenance_enabled else "Maintenance OFF"
    moderation.add_modlog(action, "system", _actor_label(message.from_user))
    await _send_mod_notification(message, settings, action, "system")
    await _notify_tracked_users(message, settings, messages.MAINTENANCE_STARTED if enabled else messages.MAINTENANCE_ENDED)
    await message.answer(f"✅ {action}.")


@router.message(Command("maintenance_msg"))
async def maintenance_message_handler(message: Message, settings: Settings) -> None:
    if not _require_moderator(message, settings):
        await message.answer(messages.UNAUTHORIZED)
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2 or not parts[1].strip():
        await message.answer("❌ Usage: /maintenance_msg <message>")
        return
    moderation.maintenance_message = parts[1].strip()
    await message.answer("✅ Maintenance message updated.")


@router.message(Command("uptime"))
async def uptime_handler(message: Message, settings: Settings) -> None:
    if not _require_moderator(message, settings):
        await message.answer(messages.UNAUTHORIZED)
        return
    elapsed = datetime.now().astimezone() - moderation.started_at
    await message.answer(f"⏱ Uptime: {str(elapsed).split('.')[0]}")


@router.message(Command("users"))
async def users_handler(message: Message, settings: Settings) -> None:
    if not _require_moderator(message, settings):
        await message.answer(messages.UNAUTHORIZED)
        return
    await message.answer(f"👥 Known users: {len(moderation.profiles)}")


@router.message(Command("topusers"))
async def top_users_handler(message: Message, settings: Settings) -> None:
    if not _require_moderator(message, settings):
        await message.answer(messages.UNAUTHORIZED)
        return
    ranked = sorted(moderation.profiles.values(), key=lambda profile: profile.request_count, reverse=True)
    lines = ["🏆 <b>Top Users</b>"]
    for index, profile in enumerate(ranked[:20], 1):
        label = f"@{profile.username}" if profile.username else "Unknown"
        lines.append(f"{index}. {html.escape(label)} — <code>{profile.user_id}</code> — {profile.request_count}")
    await message.answer("\n".join(lines) if len(lines) > 1 else "✅ No usage recorded.")


@router.message(Command("topcommands"))
async def top_commands_handler(message: Message, settings: Settings) -> None:
    if not _require_moderator(message, settings):
        await message.answer(messages.UNAUTHORIZED)
        return
    counts: dict[str, int] = {}
    for profile in moderation.profiles.values():
        for command, count in (profile.command_counts or {}).items():
            counts[command] = counts.get(command, 0) + count
    lines = ["📈 <b>Top Commands</b>"]
    for index, (command, count) in enumerate(sorted(counts.items(), key=lambda item: item[1], reverse=True), 1):
        lines.append(f"{index}. <code>{html.escape(command)}</code> — {count}")
    await message.answer("\n".join(lines) if len(lines) > 1 else "✅ No command usage recorded.")


@router.message(Command("userinfo"))
async def userinfo_handler(message: Message, settings: Settings) -> None:
    if not _require_moderator(message, settings):
        await message.answer(messages.UNAUTHORIZED)
        return
    target_id, username, _ = _target_with_remainder(message)
    target_id, resolved_username = _resolve_target(target_id, username)
    if not target_id:
        await message.answer("❌ User could not be resolved. Use a known username or numeric user ID.")
        return
    profile = moderation.profiles.get(target_id)
    warning_count = len(moderation.warnings.get(target_id, []))
    banned = _ban_store.get(target_id) is not None
    display_username = resolved_username or (profile.username if profile else None) or "Not set"
    first_name = profile.first_name if profile and profile.first_name else "Unknown"
    role = "Admin" if target_id == settings.admin_id else ("Moderator" if target_id in moderation.moderators else "Normal")
    requests = profile.request_count if profile else 0
    await message.answer(
        f"👤 <b>User Info</b>\nID: <code>{target_id}</code>\nUsername: @{html.escape(display_username) if display_username != 'Not set' else display_username}\nFirst name: {html.escape(first_name)}\nRole: {role}\nBanned: {'Yes' if banned else 'No'}\nWarnings: {warning_count}\nRequests: {requests}"
    )


@router.message(Command("cmds"))
async def commands_handler(message: Message, settings: Settings) -> None:
    normal = ["/start", "/help", "/num", "/tg", "/cmds"]
    moderation_commands = ["/ban", "/unban", "/banlist", "/broadcast", "/stats", "/maintenance", "/restart", "/uptime", "/users", "/maintenance_msg", "/warn", "/warnings", "/resetwarn", "/modlog", "/topusers", "/topcommands", "/userinfo"]
    admin_commands = ["/mod", "/unmod"]
    if _is_admin(message.from_user.id, settings):
        commands = normal + moderation_commands + admin_commands
    elif message.from_user.id in moderation.moderators:
        commands = normal + moderation_commands
    else:
        commands = normal
    await message.answer("<b>Available commands</b>\n" + "\n".join(commands))


@router.message(Command("restart"))
async def restart_handler(message: Message, settings: Settings) -> None:
    if not _require_moderator(message, settings):
        await message.answer(messages.UNAUTHORIZED)
        return
    moderation.add_modlog("Restart", "system", _actor_label(message.from_user))
    await _send_mod_notification(message, settings, "Restart requested", "system")
    await _notify_tracked_users(message, settings, messages.RESTART_NOTICE)
    await message.answer("🔄 Restart requested.")
    if os.getenv("VERCEL_URL") or os.getenv("VERCEL"):
        await message.answer("ℹ️ Automatic process restart is unavailable on Vercel; redeploy or invoke the webhook again.")
        return

    async def restart_process() -> None:
        await asyncio.sleep(0.5)
        os.environ["BOT_RESTART_PENDING"] = "1"
        os.execv(sys.executable, [sys.executable, *sys.argv])

    asyncio.create_task(restart_process())


@router.message(Command("num"))
async def number_handler(message: Message, api_client: NumberApiClient, settings: Settings) -> None:
    number = _number_from_message(message)
    if not number:
        await message.answer(messages.INVALID_NUMBER)
        return
    user_id = message.from_user.id
    now = time.monotonic()
    if now - _last_lookup.get(user_id, 0) < settings.num_rate_limit_seconds:
        await message.answer(messages.RATE_LIMITED)
        return
    _last_lookup[user_id] = now
    try:
        response = await api_client.lookup(number)
        _audit_api_response.set(_api_result_text(response.payload))
        await _send_api_response(message, response.payload, response.is_json, number)
    except NumberApiTimeoutError:
        await message.answer(messages.LOOKUP_TIMEOUT)
    except NumberApiConnectionError:
        await message.answer(messages.LOOKUP_CONNECTION_ERROR)
    except NumberApiHttpError:
        await message.answer(messages.LOOKUP_HTTP_ERROR)
    except NumberApiResponseError:
        await message.answer(messages.LOOKUP_RESPONSE_ERROR)
    except NumberApiError:
        await message.answer(messages.LOOKUP_ERROR)


@router.message(Command("tg"))
async def telegram_user_handler(message: Message, telegram_api_client: TelegramApiClient, settings: Settings) -> None:
    telegram_user_id = _telegram_user_id_from_message(message)
    if not telegram_user_id:
        await message.answer(messages.INVALID_TELEGRAM_USER_ID)
        return
    user_id = message.from_user.id
    now = time.monotonic()
    if now - _last_lookup.get(user_id, 0) < settings.num_rate_limit_seconds:
        await message.answer(messages.RATE_LIMITED)
        return
    _last_lookup[user_id] = now
    try:
        response = await telegram_api_client.lookup(telegram_user_id)
        _audit_api_response.set(_api_result_text(response.payload))
        await _send_api_response(message, response.payload, response.is_json, telegram_user_id)
    except NumberApiTimeoutError:
        await message.answer(messages.LOOKUP_TIMEOUT)
    except NumberApiConnectionError:
        await message.answer(messages.LOOKUP_CONNECTION_ERROR)
    except NumberApiHttpError:
        await message.answer(messages.LOOKUP_HTTP_ERROR)
    except NumberApiResponseError:
        await message.answer(messages.LOOKUP_RESPONSE_ERROR)
    except NumberApiError:
        await message.answer(messages.LOOKUP_ERROR)
    except Exception:
        logger.exception("Unexpected Telegram user lookup failure")
        await message.answer(messages.LOOKUP_ERROR)


@router.message(Command("stat", "stats"))
async def stat_handler(message: Message, settings: Settings) -> None:
    if not _require_moderator(message, settings):
        await message.answer("⛔ This command is available to administrators only.")
        return
    cutoff = time.monotonic() - (settings.active_hours * 3600)
    active = sum(last_seen >= cutoff for last_seen in _observed_users.values())
    await message.answer(messages.stats(len(_observed_users), active, settings.active_hours))


@router.message(Command("broadcast"))
async def broadcast_handler(message: Message, settings: Settings) -> None:
    if not _require_moderator(message, settings):
        await message.answer("⛔ This command is available to administrators only.")
        return
    parts = (message.text or "").split(maxsplit=1)
    content = parts[1].strip() if len(parts) == 2 else ""
    if not content:
        await message.answer(messages.BROADCAST_INVALID)
        return
    successful = 0
    failed = 0
    for recipient_id in get_recipients():
        try:
            await message.bot.send_message(recipient_id, messages.broadcast(content))
            successful += 1
        except Exception:
            failed += 1
            logger.warning("Could not deliver broadcast to %s", recipient_id, exc_info=True)
    await message.answer(messages.broadcast_result(successful, failed))


def build_services(settings: Settings) -> tuple[NumberApiClient, TelegramApiClient]:
    return NumberApiClient(settings), TelegramApiClient(settings)
