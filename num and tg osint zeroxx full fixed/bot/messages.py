"""User-facing message templates."""

import html

FOOTER = "🛠️ Developer — @Brutoixx / @Esahekya"
SEPARATOR = "━━━━━━━━━━━━━━━━"


def home(first_name: str, username: str | None) -> str:
    account = f"@{username}" if username else "Not set"
    return (
        f"👋 <b>Welcome, {first_name}!</b>\n\n"
        f"👤 Username: {account}\n\n"
        "🔎 This bot Data With Api Lookup Service.\n\n"
        "Only For Fair Uses Owner is Not Responsible For Any Misuse.\n\n"
        f"{SEPARATOR}\n"
        "📚 <b>Available Commands</b>\n"
        "• /help — How the bot works\n"
        "• /num — Look up a number\n"
        "• /vnum — Look up a vehicle registration\n\n"
        "• /tg — Telegram User ID lookup\n\n"
        "📝 <b>Note:</b> Enter number without +91 in /num, vehicle number in /vnum, and Telegram User ID in /tg\n\n"
        f"{FOOTER}"
    )


HELP = (
    "🆘 <b>Help & Support</b>\n\n"
    f"{SEPARATOR}\n"
    "• /start — Open the home screen\n"
    "• /num 1234567890 — Look up a number\n"
    "• /vnum DL01AB1234 — Look up a vehicle registration\n\n"
    "• /tg 7290081245 — Telegram User ID lookup\n\n"
    "Enter digits without <code>+91</code>. The bot shows only metadata "
    "provided by the configured service.\n\n"
    "Need assistance? Create a support ticket below.\n\n"
    f"{FOOTER}"
)

INVALID_NUMBER = (
    "❌ <b>Invalid number</b>\n\n"
    "Usage:\n<code>/num 1234567890</code>\n\n"
    "📝 Enter the number without +91."
)
INVALID_VEHICLE_NUMBER = "Wrong Input: Usage: /vnum &lt;vehicle_number&gt;"
INVALID_VEHICLE_FORMAT = "Invalid Input: Please enter a valid vehicle number."
INVALID_TELEGRAM_USER_ID = "❌ Wrong input. Usage: /tg 7290081245"

RATE_LIMITED = "⏳ Please wait a few seconds before requesting another lookup."
LOOKUP_ERROR = "⚠️ The lookup service is temporarily unavailable. Please try again later."
LOOKUP_TIMEOUT = "⏳ The lookup service timed out. Please try again shortly."
LOOKUP_CONNECTION_ERROR = "⚠️ The lookup service could not be reached. Please try again later."
LOOKUP_HTTP_ERROR = "⚠️ The lookup service returned an error. Please try again later."
LOOKUP_RESPONSE_ERROR = "⚠️ The lookup service returned an invalid response. Please try again later."
FILE_MAKING_FAILED = "⚠️ File making process failed."
API_RESPONSE_DELIVERY_ERROR = "⚠️ The API response could not be delivered. Please try again later."
NO_METADATA = "ℹ️ The lookup service returned no displayable metadata for this number."
TELEGRAM_LOOKUP_NO_RESULT = "ℹ️ No Telegram user details were returned for this ID."
API_RESPONSE_DELETE_NOTICE = "This message will be deleted in 1 minute."
VEHICLE_RESPONSE_DELETE_NOTICE = "⚠️ This message will be deleted in 1 minute."
TICKET_CREATED = (
    "🎫 <b>Support Ticket Created</b>\n\n"
    "Your request has been sent to support.\n\n"
    "Ticket ID: <code>#{ticket_id}</code>\n\n"
    "Our support team has been notified.\n\n"
    f"{FOOTER}"
)


def ticket_alert(ticket: dict) -> str:
    username = f"@{ticket['username']}" if ticket.get("username") else "Not set"
    return (
        "🎫 <b>NEW SUPPORT TICKET</b>\n"
        f"{SEPARATOR}\n"
        f"🎟 Ticket ID: <code>#{ticket['ticket_id']}</code>\n"
        f"👤 Name: {ticket['first_name']}\n"
        f"🔹 Username: {username}\n"
        f"🆔 User ID: <code>{ticket['telegram_user_id']}</code>\n"
        f"🕒 Date/Time: {ticket['created_at']}\n"
        "📌 Status: Open\n"
        f"{SEPARATOR}"
    )


def stats(total: int, active: int, active_hours: int) -> str:
    return (
        "📊 <b>CURRENT INSTANCE STATISTICS</b>\n\n"
        f"👥 Observed since this process started: <b>{total}</b>\n"
        f"🟢 Active in the last {active_hours} hours: <b>{active}</b>\n\n"
        "ℹ️ These are temporary in-memory figures and reset when the process restarts."
    )


BROADCAST_INVALID = "❌ Wrong input. Usage: /broadcast <message>"

FORCE_JOIN = (
    "🔒 <b>Access Locked</b>\n\n"
    "To use the bot, you must join all required communities.\n\n"
    "Join all three and then press Verify."
)
FORCE_JOIN_VERIFY_SUCCESS = "✅ <b>Verification Successful!</b>\n\nYou can now use the bot."
FORCE_JOIN_VERIFY_FAILED = "❌ <b>Verification Failed</b>\n\nYou still need to join: {targets}."
BANNED = "🚫 You are banned from using this bot."
UNAUTHORIZED = "❌ You are not authorized to use this command."
BAN_USAGE = "❌ Usage: /ban @username or /ban USER_ID"
UNBAN_USAGE = "❌ Usage: /unban @username or /unban USER_ID"
INVALID_USER_ID = "❌ Invalid user ID."
USER_NOT_RESOLVED = "❌ User could not be resolved. Use the Telegram user ID instead."
DUPLICATE_BAN = "⚠️ User is already banned."
NOT_BANNED = "⚠️ User is not currently banned."
BAN_SUCCESS = "✅ User has been banned."
UNBAN_SUCCESS = "✅ User has been unbanned."
SELF_BAN = "❌ You cannot ban yourself."
BANLIST_EMPTY = "✅ No users are currently banned."
USER_BANNED = "🚫 You have been banned from using this bot."
USER_UNBANNED = "✅ Your ban has been removed. You can use the bot again."
WARNING_NOTICE = "⚠️ You have received warning {count}/3.\nReason: {reason}\nRemaining warnings before automatic ban: {remaining}"
AUTOMATIC_BAN_NOTICE = "🚫 You have been automatically banned after receiving 3 warnings."
WARNINGS_RESET_NOTICE = "✅ Your warnings have been reset."
MOD_PROMOTED_NOTICE = "🛡️ You have been promoted to Moderator."
MOD_REMOVED_NOTICE = "ℹ️ Your Moderator role has been removed."
MAINTENANCE_STARTED = "🛠️ The bot is currently under maintenance. Please try again later."
MAINTENANCE_ENDED = "✅ Maintenance is over. The bot is available again."
RESTART_NOTICE = "🔄 The bot is restarting. Please wait a moment."
RESTART_COMPLETED = "✅ The bot has restarted successfully."


def banlist(entries: list[tuple[int, str | None]]) -> str:
    lines = ["🚫 <b>Banned Users</b>", ""]
    for index, (user_id, username) in enumerate(entries, 1):
        label = f"@{username}" if username else "Unknown username"
        lines.append(f"{index}. {html.escape(label)} — <code>{user_id}</code>")
    return "\n".join(lines)


def audit_log(user: dict[str, str], message_text: str, date: str, time: str, api_response: str | None) -> str:
    lines = [
        "🔔 <b>Audit Log</b>",
        "",
        f"👤 <b>User:</b> {user['name']}",
        f"🆔 <b>ID:</b> <code>{user['id']}</code>",
        f"🏷️ <b>Username:</b> {user['username']}",
        "",
        f"💬 <b>Message:</b> {message_text}",
        "",
        f"📅 <b>Date:</b> {date}",
        f"🕐 <b>Time:</b> {time}",
    ]
    if api_response:
        lines.extend(["", "🔎 <b>API Response:</b>", api_response])
    lines.extend(["", SEPARATOR, FOOTER])
    return "\n".join(lines)


def broadcast(content: str) -> str:
    return "\n".join(["📢 <b>Broadcast Message</b>", "", html.escape(content), "", SEPARATOR, FOOTER])


def broadcast_result(successful: int, failed: int) -> str:
    return f"📢 Broadcast completed.\n✅ Successful: {successful}\n❌ Failed: {failed}"


def format_lookup(number: str, fields: dict[str, str]) -> str:
    labels = {
        "country": "🌍 Country",
        "region": "📍 Region",
        "carrier": "📡 Carrier",
        "type": "📞 Type",
        "valid": "✅ Valid",
        "line_type": "📞 Line type",
        "location": "📍 Location",
    }
    lines = ["🔎 <b>NUMBER LOOKUP</b>", SEPARATOR, f"📱 Number: <code>{number}</code>"]
    for key, label in labels.items():
        if key in fields:
            lines.append(f"{label}: {fields[key]}")
    lines.extend(["", SEPARATOR, FOOTER])
    return "\n".join(lines)


def format_api_result(number: str, result: str) -> str:
    """Wrap pre-escaped, human-readable API output in the bot's usual layout."""
    return "\n".join([
        "🔎 <b>NUMBER LOOKUP</b>",
        SEPARATOR,
        f"📱 Number: <code>{number}</code>",
        "",
        result,
        "",
        SEPARATOR,
        FOOTER,
    ])


def format_telegram_lookup(telegram_user_id: str, result: str) -> str:
    """Wrap pre-escaped, human-readable Telegram lookup output."""
    return "\n".join([
        "🔍 <b>Telegram User ID Details</b>",
        SEPARATOR,
        f"👤 User ID: <code>{telegram_user_id}</code>",
        "",
        result,
        "",
        SEPARATOR,
        FOOTER,
    ])
