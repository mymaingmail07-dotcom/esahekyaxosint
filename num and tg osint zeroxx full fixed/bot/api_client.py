"""Isolated HTTP client for the configured number metadata service."""

import json
import logging
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from bot import Settings

logger = logging.getLogger(__name__)


class NumberApiError(Exception):
    """Base error for number API failures."""


class NumberApiTimeoutError(NumberApiError):
    """Raised when the number API does not respond before the timeout."""


class NumberApiConnectionError(NumberApiError):
    """Raised when the number API cannot be reached."""


class NumberApiHttpError(NumberApiError):
    """Raised when the number API returns a non-success HTTP status."""


class NumberApiResponseError(NumberApiError):
    """Raised when the API returns an empty or genuinely unusable response."""


@dataclass(frozen=True)
class NumberApiResponse:
    """A successfully received API response, kept separate from transport errors."""

    content_type: str
    payload: Any
    is_json: bool


def _safe_url(url: str) -> str:
    """Return a loggable URL while removing commonly used credential parameters."""
    parsed = urlsplit(url)
    secret_names = {"api_key", "apikey", "authorization", "key", "password", "secret", "token"}
    query = [
        (key, "[redacted]" if key.lower() in secret_names else value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
    ]
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), ""))


def _build_url_with_query_value(url: str, value: str) -> str:
    """Replace the first empty query parameter in-place, preserving the configured API URL."""
    parsed = urlsplit(url)
    params = parse_qsl(parsed.query, keep_blank_values=True)
    if not params:
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode({"value": value}), parsed.fragment))

    replaced = False
    rewritten_params: list[tuple[str, str]] = []
    for key, existing_value in params:
        if not replaced and existing_value == "":
            rewritten_params.append((key, value))
            replaced = True
        else:
            rewritten_params.append((key, existing_value))

    if replaced:
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(rewritten_params), parsed.fragment))

    last_key = params[-1][0]
    rewritten_params.append((last_key, value))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(rewritten_params), parsed.fragment))


def _body_preview(body: str, limit: int = 500) -> str:
    """Compact, bounded response-body logging suitable for temporary debugging."""
    preview = " ".join(body.split())
    return preview[:limit] + ("…" if len(preview) > limit else "")


def _parse_complete_body(body: str, content_type: str) -> NumberApiResponse:
    """Parse the complete body before any Telegram message-size decision."""
    if not body.strip():
        raise NumberApiResponseError
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        if "json" in content_type:
            raise NumberApiResponseError
        return NumberApiResponse(content_type=content_type, payload=body, is_json=False)
    return NumberApiResponse(content_type=content_type, payload=payload, is_json=True)


class NumberApiClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.timeout = httpx.Timeout(12.0, connect=5.0)

    async def lookup(self, number: str) -> NumberApiResponse:
        url = self.settings.number_api_url
        method = os.getenv("NUMBER_API_METHOD", "GET").upper()
        request_kwargs: dict[str, Any] = {"headers": {"Accept": "application/json"}, "timeout": self.timeout}
        if "{number}" in url:
            url = url.replace("{number}", number)
        else:
            parsed_url = httpx.URL(url)
            empty_query_parameter = next(
                (key for key, value in parsed_url.params.multi_items() if value == ""), None
            )
            number_param = os.getenv("NUMBER_API_NUMBER_PARAM", empty_query_parameter or "number")
            payload_format = os.getenv(
                "NUMBER_API_PAYLOAD_FORMAT", "query" if method == "GET" else "form"
            ).lower()
            if payload_format == "query":
                request_kwargs["params"] = {number_param: number}
            elif payload_format == "form":
                request_kwargs["data"] = {number_param: number}
            else:
                raise NumberApiError("NUMBER_API_PAYLOAD_FORMAT must be 'query' or 'form'")
        try:
            async with httpx.AsyncClient() as client:
                response = await client.request(method, url, **request_kwargs)
        except httpx.TimeoutException as exc:
            logger.warning("Number API request timed out")
            raise NumberApiTimeoutError from exc
        except httpx.ConnectError as exc:
            logger.warning("Could not connect to the number API")
            raise NumberApiConnectionError from exc
        except httpx.RequestError as exc:
            logger.warning("Number API request failed: %s", type(exc).__name__)
            raise NumberApiConnectionError from exc
        body = response.content.decode(response.encoding or "utf-8", errors="replace")
        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        logger.info(
            "Number API response status=%s content_type=%s url=%s body_preview=%r",
            response.status_code,
            content_type or "(missing)",
            _safe_url(str(response.request.url)),
            _body_preview(body),
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.warning("Number API returned HTTP status %s", exc.response.status_code)
            raise NumberApiHttpError from exc
        try:
            return _parse_complete_body(body, content_type)
        except NumberApiResponseError:
            logger.warning("Number API returned an empty or unusable response")
            raise

    async def lookup_vehicle(self, vehicle_number: str) -> NumberApiResponse:
        url = self.settings.vehicle_api_url
        method = os.getenv("VEHICLE_API_METHOD", "GET").upper()
        request_kwargs: dict[str, Any] = {"headers": {"Accept": "application/json"}, "timeout": self.timeout}
        for placeholder in ("{vehicle_number}", "{vehicle}", "{registration_number}"):
            if placeholder in url:
                url = url.replace(placeholder, vehicle_number)
                break
        else:
            parsed_url = httpx.URL(url)
            empty_query_parameter = next(
                (key for key, value in parsed_url.params.multi_items() if value == ""), None
            )
            if empty_query_parameter:
                url = _build_url_with_query_value(url, vehicle_number)
            else:
                vehicle_param = os.getenv("VEHICLE_API_NUMBER_PARAM", "vehicle")
                payload_format = os.getenv(
                    "VEHICLE_API_PAYLOAD_FORMAT", "query" if method == "GET" else "form"
                ).lower()
                if payload_format == "query":
                    request_kwargs["params"] = {vehicle_param: vehicle_number}
                elif payload_format == "form":
                    request_kwargs["data"] = {vehicle_param: vehicle_number}
                else:
                    raise NumberApiError("VEHICLE_API_PAYLOAD_FORMAT must be 'query' or 'form'")
        try:
            logger.info("Starting vehicle lookup. vehicle_number=%s url=%s method=%s", vehicle_number, _safe_url(url), method)
            async with httpx.AsyncClient() as client:
                response = await client.request(method, url, **request_kwargs)
        except httpx.TimeoutException as exc:
            logger.warning("Vehicle API request timed out")
            raise NumberApiTimeoutError from exc
        except httpx.ConnectError as exc:
            logger.warning("Could not connect to the vehicle API")
            raise NumberApiConnectionError from exc
        except httpx.RequestError as exc:
            logger.warning("Vehicle API request failed: %s", type(exc).__name__)
            raise NumberApiConnectionError from exc
        body = response.content.decode(response.encoding or "utf-8", errors="replace")
        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        logger.info(
            "Vehicle API response status=%s content_type=%s url=%s body_preview=%r",
            response.status_code,
            content_type or "(missing)",
            _safe_url(str(response.request.url)),
            _body_preview(body),
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.warning("Vehicle API returned HTTP status %s", exc.response.status_code)
            raise NumberApiHttpError from exc
        try:
            return _parse_complete_body(body, content_type)
        except NumberApiResponseError:
            logger.warning("Vehicle API returned an empty or unusable response")
            raise


class TelegramApiClient(NumberApiClient):
    """HTTP client for the separately configured Telegram lookup endpoint."""

    async def lookup(self, telegram_user_id: str) -> NumberApiResponse:
        url = self.settings.tg_api_url
        if "{telegram_id}" in url:
            url = url.replace("{telegram_id}", telegram_user_id)
            request_kwargs: dict[str, Any] = {
                "headers": {"Accept": "application/json"},
                "timeout": self.timeout,
            }
        else:
            parsed_url = httpx.URL(url)
            parameter_name = next(
                (key for key, value in parsed_url.params.multi_items() if value == ""), None
            )
            if not parameter_name:
                raise NumberApiError(
                    "TG_API_URL must contain {telegram_id} or an empty query parameter"
                )
            request_kwargs = {
                "headers": {"Accept": "application/json"},
                "params": {parameter_name: telegram_user_id},
                "timeout": self.timeout,
            }
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, **request_kwargs)
        except httpx.TimeoutException as exc:
            logger.warning("Telegram API request timed out")
            raise NumberApiTimeoutError from exc
        except httpx.ConnectError as exc:
            logger.warning("Could not connect to the Telegram API")
            raise NumberApiConnectionError from exc
        except httpx.RequestError as exc:
            logger.warning("Telegram API request failed: %s", type(exc).__name__)
            raise NumberApiConnectionError from exc
        body = response.content.decode(response.encoding or "utf-8", errors="replace")
        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        logger.info(
            "Telegram API response status=%s content_type=%s url=%s body_preview=%r",
            response.status_code,
            content_type or "(missing)",
            _safe_url(str(response.request.url)),
            _body_preview(body),
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.warning("Telegram API returned HTTP status %s", exc.response.status_code)
            raise NumberApiHttpError from exc
        try:
            return _parse_complete_body(body, content_type)
        except NumberApiResponseError:
            logger.warning("Telegram API returned an empty or unusable response")
            raise
