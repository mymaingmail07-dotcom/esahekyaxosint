from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def help_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🎫 Create Ticket", callback_data="ticket:create")]]
    )


def contact_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="💬 Contact User", url=f"tg://user?id={user_id}")]]
    )


def force_join_keyboard(urls: tuple[str, str, str]) -> InlineKeyboardMarkup:
    labels = ("📢 Zerox X Chatgc", "📢 Zerox X Osint", "📢 Zerox X Updates")
    buttons = [
        [InlineKeyboardButton(text=label, url=url)]
        for label, url in zip(labels, urls, strict=True)
        if url
    ]
    buttons.append([InlineKeyboardButton(text="✅ Verify", callback_data="force_join_verify")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)
