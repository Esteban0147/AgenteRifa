import unittest

from app.simulated_tools import SimulatedRaffle


class SimulatedRaffleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.raffle = SimulatedRaffle()

    def reserve(self, number: str = "07", ticket_value: float = 1.5) -> dict:
        return self.raffle.execute(
            "gestionar_numero_rifa",
            {
                "action": "reserve",
                "number": number,
                "ticket_value": ticket_value,
            },
            "customer-1",
        )

    def test_reserves_two_digit_number_with_selected_ticket_value(self) -> None:
        result = self.reserve()

        self.assertTrue(result["reserved"])
        self.assertEqual(result["number"], "07")
        self.assertEqual(result["ticket_value"], "1.50")
        self.assertEqual(
            result["payment_amount"],
            "$1.50 dólares (monto ficticio para la demostración)",
        )
        self.assertIn("ficticia", result["bank_details"]["account"])

    def test_rejects_number_that_is_not_exactly_two_digits(self) -> None:
        result = self.reserve(number="7")

        self.assertFalse(result["ok"])
        self.assertIn("exactamente 2 cifras", result["error"])

    def test_rejects_ticket_value_outside_half_dollar_steps(self) -> None:
        result = self.reserve(ticket_value=1.25)

        self.assertFalse(result["ok"])
        self.assertIn("incrementos de $0.50", result["error"])

    def test_does_not_confirm_wrong_simulated_bank_amount(self) -> None:
        reservation = self.reserve()
        self.raffle.begin_message(
            "customer-1",
            {
                "reference": reservation["bank_details"]["reference"],
                "amount": "4.50",
                "date": "2026-10-19",
            },
        )

        result = self.raffle.execute("verificar_pago_banco", {}, "customer-1")

        self.assertFalse(result["verified"])
        self.assertEqual(result["expected_amount"], "$1.50 dólares")

    def test_verifies_receipt_when_amount_matches_four_dollar_fifty_ticket(self) -> None:
        reservation = self.reserve(ticket_value=4.5)
        self.raffle.begin_message(
            "customer-1",
            {
                "reference": reservation["bank_details"]["reference"],
                "amount": "4.50",
                "date": "2026-10-19",
            },
        )

        result = self.raffle.execute("verificar_pago_banco", {}, "customer-1")

        self.assertTrue(result["verified"])
        self.assertEqual(result["amount"], "$4.50 dólares")


    def test_accepts_demo_reference_containing_pago(self) -> None:
        self.reserve()
        self.raffle.begin_message(
            "customer-1",
            {"reference": "PAGO-DEMO", "amount": "1.50", "date": "2026-10-19"},
        )

        result = self.raffle.execute("verificar_pago_banco", {}, "customer-1")

        self.assertTrue(result["verified"])
        self.assertTrue(result["accepted_by_demo_marker"])

    def test_reusable_pago_marker_is_accepted_for_different_ticket_values(self) -> None:
        self.reserve(ticket_value=5)
        self.raffle.begin_message(
            "customer-1",
            {
                "reference": "PAGO",
                "amount": "5.00",
                "date": "2026-10-19",
            },
        )
        first_result = self.raffle.execute(
            "verificar_pago_banco", {}, "customer-1"
        )

        self.raffle.execute(
            "gestionar_numero_rifa",
            {"action": "reserve", "number": "89", "ticket_value": 4.5},
            "customer-2",
        )
        self.raffle.begin_message(
            "customer-2",
            {
                "reference": "PAGO",
                "amount": "4.50",
                "date": "2026-10-19",
            },
        )
        second_result = self.raffle.execute(
            "verificar_pago_banco", {}, "customer-2"
        )

        self.assertTrue(first_result["verified"])
        self.assertTrue(second_result["verified"])
        self.assertTrue(second_result["accepted_by_demo_marker"])

    def test_actual_reservation_reference_cannot_be_reused(self) -> None:
        first_reservation = self.reserve()
        receipt = {
            "reference": first_reservation["bank_details"]["reference"],
            "amount": "1.50",
            "date": "2026-10-19",
        }
        self.raffle.begin_message("customer-1", receipt)
        first_result = self.raffle.execute(
            "verificar_pago_banco", {}, "customer-1"
        )
        self.assertTrue(first_result["verified"])

        self.raffle.execute(
            "gestionar_numero_rifa",
            {"action": "reserve", "number": "08", "ticket_value": 1.5},
            "customer-2",
        )
        self.raffle.begin_message("customer-2", receipt)
        second_result = self.raffle.execute(
            "verificar_pago_banco", {}, "customer-2"
        )

        self.assertFalse(second_result["verified"])

    def test_pago_demo_reference_still_requires_exact_amount(self) -> None:
        self.reserve()
        self.raffle.begin_message(
            "customer-1",
            {"reference": "PAGO-DEMO", "amount": "1.49", "date": "2026-10-19"},
        )

        result = self.raffle.execute("verificar_pago_banco", {}, "customer-1")

        self.assertFalse(result["verified"])

    def test_ticket_is_blocked_until_simulated_payment_is_verified(self) -> None:
        result = self.raffle.execute("enviar_ticket_whatsapp", {}, "customer-1")

        self.assertFalse(result["ok"])

    def test_verified_payment_prepares_live_creation_and_records_ticket(self) -> None:
        reservation = self.reserve()
        self.raffle.begin_message(
            "customer-1",
            {
                "reference": reservation["bank_details"]["reference"],
                "amount": "1.50",
                "date": "2026-10-19",
            },
        )
        payment = self.raffle.execute("verificar_pago_banco", {}, "customer-1")
        ready = self.raffle.execute("enviar_ticket_whatsapp", {}, "customer-1")

        self.assertTrue(payment["verified"])
        self.assertTrue(ready["ready"])
        self.assertEqual(ready["ticket_value"], 1.5)

        ticket = self.raffle.record_ticket(
            "customer-1",
            {
                "IdTicket": 42,
                "userId": 9,
                "Numero": "07",
                "ValorBoleto": 1.5,
                "codigo": "ABCD1234",
                "Cifra": 2,
                "fechaCreacion": "2026-10-19T14:00:00.000Z",
            },
        )
        self.assertTrue(ticket["sent"])
        ticket_id = ticket["ticket_url"].rsplit("/", 1)[-1].removesuffix(".html")
        ticket_html = self.raffle.ticket_html(ticket_id)
        self.assertIn("NO#<span>07</span>", ticket_html)
        self.assertIn("VALOR: $<span>1.5</span>", ticket_html)
        self.assertIn("<span>ABCD1234</span>", ticket_html)
        self.assertIn("AGENCIA: <span>9</span>", ticket_html)
        self.assertIn("lunes, 19 de octubre de 2026", ticket_html)
        self.assertIn("PRIMERA", ticket_html)
        self.assertIn("$102.00", ticket_html)
        self.assertIn("font-family: 'Courier New', Courier, monospace", ticket_html)

        repeated = self.raffle.execute("enviar_ticket_whatsapp", {}, "customer-1")
        self.assertEqual(repeated["ticket"]["IdTicket"], 42)

    def test_ticket_template_escapes_api_values(self) -> None:
        ticket_html = self.raffle._render_ticket_html(
            {
                "Numero": "07",
                "ValorBoleto": 1,
                "codigo": "<script>alert(1)</script>",
                "userId": 42,
                "fechaCreacion": "2026-10-19T14:00:00Z",
            }
        )

        self.assertNotIn("<script>alert(1)</script>", ticket_html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", ticket_html)

    def test_each_reservation_gets_a_unique_payment_reference(self) -> None:
        first = self.reserve()
        second = self.raffle.execute(
            "gestionar_numero_rifa",
            {"action": "reserve", "number": "08", "ticket_value": 0.5},
            "customer-2",
        )

        self.assertNotEqual(
            first["bank_details"]["reference"], second["bank_details"]["reference"]
        )


if __name__ == "__main__":
    unittest.main()
