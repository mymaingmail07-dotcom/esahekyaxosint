import asyncio
import logging
import os

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot import get_settings
from bot.handlers import build_services, create_dispatcher
from bot import messages

logging.basicConfig(level=logging.INFO)


async def main() -> None:
    settings = get_settings()
    api_client, telegram_api_client = build_services(settings)
    dispatcher = create_dispatcher(settings)
    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dispatcher.workflow_data.update(
        api_client=api_client, telegram_api_client=telegram_api_client, settings=settings
    )
    if os.getenv("BOT_RESTART_PENDING") == "1":
        try:
            await bot.send_message(settings.alt_tg_id or settings.admin_id, messages.RESTART_COMPLETED)
        except Exception:
            logging.getLogger(__name__).exception("Could not send restart completion notification")
        os.environ.pop("BOT_RESTART_PENDING", None)
    print("Starting Number OSINT Bot...")
    try:
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
