import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bot.api_client import NumberApiResponse, _build_url_with_query_value
from bot import messages
from bot.handlers import _inject_developer_credit, _normalize_vehicle_number, vehicle_number_handler


class VehicleLookupTests(unittest.TestCase):
    def test_normalize_vehicle_number_trims_and_upcases(self):
        self.assertEqual(_normalize_vehicle_number("  dl01 ab 1234  "), "DL01AB1234")
        self.assertEqual(_normalize_vehicle_number("BR01GF1000"), "BR01GF1000")
        self.assertEqual(_normalize_vehicle_number("UP32AB1234"), "UP32AB1234")
        self.assertIsNone(_normalize_vehicle_number("DL"))

    def test_inject_developer_credit_keeps_original_fields(self):
        payload = {"vehicle": "DL01AB1234", "status": "active"}
        result = _inject_developer_credit(payload)
        self.assertEqual(result["vehicle"], "DL01AB1234")
        self.assertEqual(result["status"], "active")
        self.assertEqual(result["Developer"], "@brutoixx")

    def test_build_url_with_query_value_does_not_duplicate_placeholder_param(self):
        url = "https://encorexproxy.vercel.app/p/84639?Bachetmkc="
        built = _build_url_with_query_value(url, "BR01GF1000")
        self.assertEqual(built, "https://encorexproxy.vercel.app/p/84639?Bachetmkc=BR01GF1000")


class VehicleHandlerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.api_client = SimpleNamespace(lookup_vehicle=AsyncMock())
        self.settings = SimpleNamespace(num_rate_limit_seconds=0)
        self.message = SimpleNamespace(
            text="",
            from_user=SimpleNamespace(id=12345),
            answer=AsyncMock(),
        )

    async def test_invalid_vehicle_does_not_call_api(self):
        self.message.text = "/vnum DL"

        await vehicle_number_handler(self.message, self.api_client, self.settings)

        self.api_client.lookup_vehicle.assert_not_awaited()
        self.message.answer.assert_awaited_once_with(
            "Invalid Input: Please enter a valid vehicle number."
        )

    async def test_missing_vehicle_returns_escaped_usage_message(self):
        self.message.text = "/vnum"

        await vehicle_number_handler(self.message, self.api_client, self.settings)

        self.api_client.lookup_vehicle.assert_not_awaited()
        self.message.answer.assert_awaited_once_with(messages.INVALID_VEHICLE_NUMBER)

    async def test_valid_vehicle_is_forwarded_dynamically(self):
        self.message.text = "/vnum br01 gf 1000"
        self.api_client.lookup_vehicle.return_value = NumberApiResponse(
            content_type="application/json",
            payload={"vehicle": "BR01GF1000"},
            is_json=True,
        )

        with patch("bot.handlers._send_vehicle_api_response", new_callable=AsyncMock):
            await vehicle_number_handler(self.message, self.api_client, self.settings)

        self.api_client.lookup_vehicle.assert_awaited_once_with("BR01GF1000")


if __name__ == "__main__":
    unittest.main()
