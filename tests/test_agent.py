import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.agent import OpenAIAgent
from app.bonanza_api import BonanzaAPIError
from app.simulated_tools import SimulatedRaffle


class OpenAIAgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_checks_bonanza_capacity_before_registering_reservation(self) -> None:
        raffle = SimulatedRaffle()
        ticket_client = SimpleNamespace(
            check_availability=AsyncMock(
                return_value={
                    "Numero": "89",
                    "CupoRestante": 4.5,
                    "ValorSolicitado": 4.5,
                    "Disponible": True,
                }
            )
        )
        agent = OpenAIAgent(
            SimpleNamespace(),
            "gpt-6-luna",
            raffle,
            ticket_client=ticket_client,
        )

        result = await agent._execute_tool(
            "gestionar_numero_rifa",
            {"action": "reserve", "number": "89", "ticket_value": 4.5},
            "customer-1",
        )

        self.assertTrue(result["reserved"])
        self.assertEqual(result["availability"]["CupoRestante"], 4.5)
        ticket_client.check_availability.assert_awaited_once_with("89", 4.5)

    async def test_does_not_register_number_when_bonanza_has_no_capacity(self) -> None:
        raffle = SimulatedRaffle()
        ticket_client = SimpleNamespace(
            check_availability=AsyncMock(
                return_value={
                    "Numero": "89",
                    "CupoRestante": 1.5,
                    "ValorSolicitado": 4.5,
                    "Disponible": False,
                }
            )
        )
        agent = OpenAIAgent(
            SimpleNamespace(),
            "gpt-6-luna",
            raffle,
            ticket_client=ticket_client,
        )

        result = await agent._execute_tool(
            "gestionar_numero_rifa",
            {"action": "reserve", "number": "89", "ticket_value": 4.5},
            "customer-1",
        )

        self.assertFalse(result["reserved"])
        self.assertIn("$1.5", result["error"])
        self.assertIsNone(raffle._customers.get("customer-1"))

    async def test_function_tools_use_supported_reasoning_effort(self) -> None:
        client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=AsyncMock(
                        return_value=SimpleNamespace(
                            choices=[
                                SimpleNamespace(
                                    message=SimpleNamespace(
                                        tool_calls=None,
                                        content="¡Hola! ¿Qué número de 2 cifras buscas?",
                                    )
                                )
                            ]
                        )
                    )
                )
            )
        )
        agent = OpenAIAgent(client, "gpt-6-luna", SimulatedRaffle())

        answer = await agent.respond("customer-1", "Hola", False)

        self.assertEqual(answer, "¡Hola! ¿Qué número de 2 cifras buscas?")
        client.chat.completions.create.assert_awaited_once()
        request = client.chat.completions.create.await_args.kwargs
        self.assertEqual(request["reasoning_effort"], "none")
        self.assertTrue(request["tools"])

    async def test_real_ticket_creation_requires_simulated_payment_verification(self) -> None:
        raffle = SimulatedRaffle()
        ticket_client = SimpleNamespace(create_ticket=AsyncMock())
        agent = OpenAIAgent(
            SimpleNamespace(),
            "gpt-6-luna",
            raffle,
            ticket_client=ticket_client,
        )

        result = await agent._execute_tool("enviar_ticket_whatsapp", {}, "customer-1")

        self.assertFalse(result["ok"])
        ticket_client.create_ticket.assert_not_awaited()

    async def test_creates_ticket_once_and_returns_the_same_ticket_on_repeat(self) -> None:
        raffle = SimulatedRaffle()
        reservation = raffle.execute(
            "gestionar_numero_rifa",
            {"action": "reserve", "number": "07", "ticket_value": 1.5},
            "customer-1",
        )
        raffle.begin_message(
            "customer-1",
            {
                "reference": reservation["bank_details"]["reference"],
                "amount": "1.50",
                "date": "2026-10-19",
            },
        )
        raffle.execute("verificar_pago_banco", {}, "customer-1")
        ticket_client = SimpleNamespace(
            create_ticket=AsyncMock(
                return_value={
                    "IdTicket": 42,
                    "Numero": "07",
                    "ValorBoleto": 1.5,
                    "codigo": "ABCD1234",
                }
            )
        )
        agent = OpenAIAgent(
            SimpleNamespace(),
            "gpt-6-luna",
            raffle,
            ticket_client=ticket_client,
        )

        result = await agent._execute_tool("enviar_ticket_whatsapp", {}, "customer-1")
        repeated = await agent._execute_tool("enviar_ticket_whatsapp", {}, "customer-1")

        self.assertTrue(result["sent"])
        self.assertEqual(result["ticket"]["IdTicket"], 42)
        self.assertEqual(repeated["ticket"]["IdTicket"], 42)
        ticket_client.create_ticket.assert_awaited_once_with("07", 1.5)

    async def test_does_not_retry_a_ticket_creation_with_uncertain_result(self) -> None:
        raffle = SimulatedRaffle()
        reservation = raffle.execute(
            "gestionar_numero_rifa",
            {"action": "reserve", "number": "07", "ticket_value": 1.5},
            "customer-1",
        )
        raffle.begin_message(
            "customer-1",
            {
                "reference": reservation["bank_details"]["reference"],
                "amount": "1.50",
                "date": "2026-10-19",
            },
        )
        raffle.execute("verificar_pago_banco", {}, "customer-1")
        ticket_client = SimpleNamespace(
            create_ticket=AsyncMock(
                side_effect=BonanzaAPIError(
                    "Se perdió la conexión. Revisa Bonanza antes de reintentar."
                )
            )
        )
        agent = OpenAIAgent(
            SimpleNamespace(),
            "gpt-6-luna",
            raffle,
            ticket_client=ticket_client,
        )

        first = await agent._execute_tool("enviar_ticket_whatsapp", {}, "customer-1")
        second = await agent._execute_tool("enviar_ticket_whatsapp", {}, "customer-1")

        self.assertFalse(first["ok"])
        self.assertFalse(second["ok"])
        self.assertIn("Revisa Bonanza", first["error"])
        ticket_client.create_ticket.assert_awaited_once_with("07", 1.5)


if __name__ == "__main__":
    unittest.main()
