import unittest

import httpx

from app.bonanza_api import BonanzaAPIError, BonanzaTicketClient


class BonanzaTicketClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_checks_existing_number_capacity_through_authenticated_api(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.url.path == "/api/login":
                return httpx.Response(200, json={"token": "test-token"})
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "Numero": "89",
                        "Cifra": 2,
                        "ValorAcumulado": 1.5,
                        "CupoMaximo": 6,
                        "CupoRestante": 4.5,
                        "ValorSolicitado": 4.5,
                        "Disponible": True,
                    },
                },
            )

        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        ticket_client = BonanzaTicketClient(
            "http://bonanza.test/api", "agent-user", "secret", http_client
        )
        try:
            availability = await ticket_client.check_availability("89", 4.5)
        finally:
            await http_client.aclose()

        self.assertTrue(availability["Disponible"])
        self.assertEqual(availability["ValorAcumulado"], 1.5)
        self.assertEqual(availability["CupoRestante"], 4.5)
        self.assertEqual(requests[1].url.path, "/api/tickets/89/disponibilidad")
        self.assertEqual(requests[1].url.params["ValorBoleto"], "4.5")
        self.assertEqual(requests[1].url.params["Cifra"], "2")
        self.assertEqual(requests[1].headers["Authorization"], "Bearer test-token")

    async def test_rejects_malformed_availability_response(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/login":
                return httpx.Response(200, json={"token": "test-token"})
            return httpx.Response(200, json={"success": True, "data": {}})

        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        ticket_client = BonanzaTicketClient(
            "http://bonanza.test/api", "agent-user", "secret", http_client
        )
        try:
            with self.assertRaisesRegex(BonanzaAPIError, "datos válidos de disponibilidad"):
                await ticket_client.check_availability("89", 4.5)
        finally:
            await http_client.aclose()

    async def test_logs_in_and_creates_two_digit_ticket_through_api(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.url.path == "/api/login":
                return httpx.Response(200, json={"token": "test-token"})
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "IdTicket": 17,
                        "Numero": "07",
                        "ValorBoleto": 1.5,
                        "Cifra": 2,
                        "codigo": "ABC12345",
                    },
                },
            )

        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        ticket_client = BonanzaTicketClient(
            "http://bonanza.test/api", "agent-user", "secret", http_client
        )
        try:
            ticket = await ticket_client.create_ticket("07", 1.5)
        finally:
            await http_client.aclose()

        self.assertEqual(ticket["IdTicket"], 17)
        self.assertEqual(requests[0].url.path, "/api/login")
        self.assertEqual(requests[1].url.path, "/api/tickets")
        self.assertEqual(requests[1].headers["Authorization"], "Bearer test-token")
        self.assertEqual(
            requests[1].read(),
            b'{"Numero":"07","ValorBoleto":1.5,"Cifra":2,"TIPO":"Normal","Vendido":"open"}',
        )

    async def test_rejects_invalid_number_or_value_before_api_call(self) -> None:
        http_client = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: self.fail("No debe hacer llamadas para datos inválidos")
            )
        )
        ticket_client = BonanzaTicketClient(
            "http://bonanza.test/api", "agent-user", "secret", http_client
        )
        try:
            with self.assertRaises(BonanzaAPIError):
                await ticket_client.create_ticket("7", 1)
            with self.assertRaises(BonanzaAPIError):
                await ticket_client.create_ticket("07", 6.5)
            with self.assertRaises(BonanzaAPIError):
                await ticket_client.create_ticket("07", 1.25)
        finally:
            await http_client.aclose()

    async def test_reports_backend_rejection_without_claiming_ticket_created(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/login":
                return httpx.Response(200, json={"token": "test-token"})
            return httpx.Response(
                400,
                json={"message": "El cupo del número 07 está agotado"},
            )

        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        ticket_client = BonanzaTicketClient(
            "http://bonanza.test/api", "agent-user", "secret", http_client
        )
        try:
            with self.assertRaisesRegex(BonanzaAPIError, "cupo del número 07"):
                await ticket_client.create_ticket("07", 1)
        finally:
            await http_client.aclose()

    async def test_rejects_backend_response_with_mismatched_ticket_details(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/login":
                return httpx.Response(200, json={"token": "test-token"})
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "IdTicket": 17,
                        "Numero": "70",
                        "ValorBoleto": 1.5,
                        "Cifra": 2,
                        "codigo": "ABC12345",
                    },
                },
            )

        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        ticket_client = BonanzaTicketClient(
            "http://bonanza.test/api", "agent-user", "secret", http_client
        )
        try:
            with self.assertRaisesRegex(BonanzaAPIError, "datos distintos"):
                await ticket_client.create_ticket("07", 1.5)
        finally:
            await http_client.aclose()


if __name__ == "__main__":
    unittest.main()
