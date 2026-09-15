"""Vercel serverless entrypoint for Telegram webhook updates."""

import asyncio
import json
import logging
import os
from http.server import BaseHTTPRequestHandler

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Update

from bot import get_settings
from bot.handlers import build_services, create_dispatcher

logger = logging.getLogger(__name__)
_settings = get_settings()
_api_client, _telegram_api_client = build_services(_settings)
_dispatcher = create_dispatcher(_settings)
_bot = Bot(_settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
_dispatcher.workflow_data.update(
    api_client=_api_client, telegram_api_client=_telegram_api_client, settings=_settings
)


def _webhook_url() -> str:
    configured_url = os.getenv("WEBHOOK_URL", "").strip()
    if configured_url:
        return configured_url.rstrip("/")
    vercel_url = os.getenv("VERCEL_URL", "").strip()
    if not vercel_url:
        raise RuntimeError("Set WEBHOOK_URL or deploy with VERCEL_URL available")
    return f"https://{vercel_url}/api/webhook"


def _send_json(response: BaseHTTPRequestHandler, status: int, payload: dict[str, str]) -> None:
    body = json.dumps(payload).encode("utf-8")
    response.send_response(status)
    response.send_header("Content-Type", "application/json")
    response.send_header("Content-Length", str(len(body)))
    response.end_headers()
    response.wfile.write(body)


async def _initialize_webhook() -> None:
    await _bot.set_webhook(_webhook_url())


async def _process_update(payload: dict) -> None:
    update = Update.model_validate(payload, context={"bot": _bot})
    await _dispatcher.feed_update(_bot, update)


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        """Register the Telegram webhook after a deployment."""
        try:
            asyncio.run(_initialize_webhook())
            _send_json(self, 200, {"status": "webhook registered", "url": _webhook_url()})
        except Exception:
            logger.exception("Could not initialize Telegram webhook")
            _send_json(self, 500, {"status": "webhook registration failed"})

    def do_POST(self) -> None:
        content_length = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(content_length))
            asyncio.run(_process_update(payload))
            _send_json(self, 200, {"status": "ok"})
        except Exception:
            logger.exception("Could not process Telegram webhook update")
            # Telegram retries non-2xx responses; acknowledge malformed updates too.
            _send_json(self, 200, {"status": "ok"})

    def do_HEAD(self) -> None:
        self.send_response(200)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        logger.info("%s - %s", self.address_string(), format % args)
