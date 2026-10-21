from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from html import escape
from typing import Any


RESERVATION_MINUTES = 10
SIMULATED_ACCEPTANCE_MARKER = "pago"


@dataclass
class Reservation:
    user_id: str
    number: str
    ticket_value: Decimal
    reference: str
    expires_at: datetime
    sold: bool = False


@dataclass
class CustomerState:
    reservation: Reservation | None = None
    receipt: dict[str, str] | None = None
    verified: bool = False
    ticket_creation_attempted: bool = False
    ticket_id: str | None = None
    ticket: dict[str, Any] | None = None


class SimulatedRaffle:
    """In-memory demo of the raffle, receipt, bank and ticket integrations."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._customers: dict[str, CustomerState] = {}
        self._tickets: dict[str, str] = {}
        self._used_references: set[str] = set()

    def begin_message(self, user_id: str, receipt: dict[str, str] | None) -> None:
        with self._lock:
            state = self._customers.setdefault(user_id, CustomerState())
            state.receipt = receipt
            state.verified = False

    def reset_customer(self, user_id: str) -> None:
        with self._lock:
            self._customers.pop(user_id, None)

    def execute(self, name: str, arguments: dict[str, Any], user_id: str) -> dict[str, Any]:
        if name == "gestionar_numero_rifa":
            return self._manage_number(user_id, arguments)
        if name == "procesar_comprobante_ocr":
            return self._process_receipt(user_id)
        if name == "verificar_pago_banco":
            return self._verify_payment(user_id)
        if name == "enviar_ticket_whatsapp":
            return self._send_ticket(user_id)
        return {"ok": False, "error": "Herramienta desconocida."}

    def ticket_html(self, ticket_id: str) -> str | None:
        with self._lock:
            return self._tickets.get(ticket_id)

    def _manage_number(self, user_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
        action = arguments.get("action")
        number = arguments.get("number")
        if action != "reserve":
            return {"ok": False, "error": "Acción no válida."}
        if not isinstance(number, str) or len(number) != 2 or not number.isdigit():
            return {"ok": False, "error": "El número debe tener exactamente 2 cifras (00 a 99)."}
        try:
            ticket_value = Decimal(str(arguments.get("ticket_value")))
        except (InvalidOperation, ValueError):
            return {"ok": False, "error": "Indica un valor de boleto válido."}
        if (
            not ticket_value.is_finite()
            or ticket_value < Decimal("0.50")
            or ticket_value > Decimal("6.00")
            or ticket_value * 2 != (ticket_value * 2).to_integral_value()
        ):
            return {
                "ok": False,
                "error": "El valor debe estar entre $0.50 y $6.00 en incrementos de $0.50.",
            }

        with self._lock:
            reservation = Reservation(
                user_id=user_id,
                number=number,
                ticket_value=ticket_value,
                reference=f"DEMO-{uuid.uuid4().hex[:12].upper()}",
                expires_at=datetime.now(timezone.utc)
                + timedelta(minutes=RESERVATION_MINUTES),
            )
            state = self._customers.setdefault(user_id, CustomerState())
            state.reservation = reservation
            state.verified = False
            state.ticket_creation_attempted = False
            state.ticket_id = None
            state.ticket = None
            return {
                "ok": True,
                "number": number,
                "reserved": True,
                "expires_in_minutes": RESERVATION_MINUTES,
                "ticket_value": f"{ticket_value:.2f}",
                "reservation_is_simulated": True,
                "payment_amount": (
                    f"${ticket_value:.2f} dólares (monto ficticio para la demostración)"
                ),
                "bank_details": {
                    "bank": "Banco de demostración (simulado)",
                    "reference": reservation.reference,
                    "account": "000000000000000000 (ficticia; no transferir)",
                },
            }

    def _process_receipt(self, user_id: str) -> dict[str, Any]:
        with self._lock:
            state = self._customers.get(user_id)
            if state is None or state.receipt is None:
                return {
                    "ok": False,
                    "error": "No hay comprobante simulado adjunto a este mensaje.",
                }
            receipt = state.receipt
            try:
                amount = Decimal(receipt["amount"])
                receipt_date = date.fromisoformat(receipt["date"])
            except (KeyError, ValueError, InvalidOperation):
                return {
                    "ok": False,
                    "error": "El comprobante simulado requiere referencia, monto y fecha válidos.",
                }
            if amount <= 0:
                return {"ok": False, "error": "El monto del comprobante debe ser mayor a cero."}
            return {
                "ok": True,
                "mode": "OCR simulado; no se analizó ninguna imagen real",
                "reference": receipt.get("reference", ""),
                "amount": f"{amount:.2f}",
                "currency": "USD",
                "date": receipt_date.isoformat(),
            }

    def _verify_payment(self, user_id: str) -> dict[str, Any]:
        with self._lock:
            state = self._customers.get(user_id)
            if state is None or state.reservation is None:
                return {"ok": False, "verified": False, "error": "No hay un número apartado."}
            reservation = state.reservation
            if reservation.expires_at <= datetime.now(timezone.utc) and not reservation.sold:
                return {
                    "ok": True,
                    "verified": False,
                    "reason": "El apartado de prueba venció; registra la solicitud de nuevo.",
                }
            if state.receipt is None:
                return {
                    "ok": False,
                    "verified": False,
                    "error": "Adjunta un comprobante simulado antes de verificar.",
                }
            reference = state.receipt.get("reference", "")
            try:
                amount = Decimal(state.receipt.get("amount", ""))
                date.fromisoformat(state.receipt.get("date", ""))
            except (ValueError, InvalidOperation):
                return {"ok": True, "verified": False, "reason": "Los datos del comprobante no son válidos."}

            accepted_by_demo_marker = (
                SIMULATED_ACCEPTANCE_MARKER in reference.casefold()
            )
            valid = (
                (
                    reference == reservation.reference
                    or accepted_by_demo_marker
                )
                and amount == reservation.ticket_value
                and (accepted_by_demo_marker or reference not in self._used_references)
            )
            if not valid:
                return {
                    "ok": True,
                    "verified": False,
                    "reason": (
                        "El banco simulado requiere la referencia correcta y un "
                        "monto igual al valor del boleto."
                    ),
                    "expected_amount": f"${reservation.ticket_value:.2f} dólares",
                }

            if not accepted_by_demo_marker:
                self._used_references.add(reference)
            reservation.sold = True
            state.verified = True
            return {
                "ok": True,
                "verified": True,
                "number": reservation.number,
                "ticket_value": f"{reservation.ticket_value:.2f}",
                "amount": f"${reservation.ticket_value:.2f} dólares",
                "bank_is_simulated": True,
                "accepted_by_demo_marker": accepted_by_demo_marker,
            }

    def _send_ticket(self, user_id: str) -> dict[str, Any]:
        with self._lock:
            state = self._customers.get(user_id)
            if state is None or not state.verified or state.reservation is None:
                return {
                    "ok": False,
                    "error": "No se puede crear el boleto sin completar la validación simulada.",
                }
            if state.ticket_id is not None and state.ticket is not None:
                return self._ticket_result(state)
            if state.ticket_creation_attempted:
                return {
                    "ok": False,
                    "error": (
                        "Ya se intentó crear este boleto. Revisa Bonanza antes de "
                        "volver a intentarlo para evitar duplicados."
                    ),
                }
            return {
                "ok": True,
                "ready": True,
                "number": state.reservation.number,
                "ticket_value": float(state.reservation.ticket_value),
            }

    def mark_ticket_creation_attempted(self, user_id: str) -> bool:
        with self._lock:
            state = self._customers.get(user_id)
            if (
                state is None
                or not state.verified
                or state.reservation is None
                or state.ticket_creation_attempted
            ):
                return False
            state.ticket_creation_attempted = True
            return True

    def record_ticket(self, user_id: str, ticket: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            state = self._customers.get(user_id)
            if state is None or not state.verified or state.reservation is None:
                return {
                    "ok": False,
                    "error": "El boleto de Bonanza no se puede asociar a una solicitud verificada.",
                }
            if state.ticket_id is not None and state.ticket is not None:
                return self._ticket_result(state)

            ticket_id = str(uuid.uuid4())
            state.ticket_id = ticket_id
            state.ticket = ticket
            self._tickets[ticket_id] = self._render_ticket_html(ticket)
            return self._ticket_result(state)

    @staticmethod
    def _ticket_result(state: CustomerState) -> dict[str, Any]:
        return {
            "ok": True,
            "sent": True,
            "mode": "Boleto creado en Bonanza; enlace mostrado en el chat simulado, sin envío por WhatsApp.",
            "ticket_url": f"/api/tickets/{state.ticket_id}.html",
            "ticket": state.ticket,
            "payment_verification_is_simulated": True,
        }

    @staticmethod
    def _render_ticket_html(ticket: dict[str, Any]) -> str:
        safe_number = escape(str(ticket.get("Numero", "")))
        safe_value = escape(str(ticket.get("ValorBoleto", "")))
        safe_code = escape(str(ticket.get("codigo", "")))
        safe_agency = escape(str(ticket.get("userId", "")))
        created_at = ticket.get("fechaCreacion")
        try:
            parsed_date = datetime.fromisoformat(
                str(created_at).replace("Z", "+00:00")
            ).date()
        except ValueError:
            parsed_date = date.today()
        weekdays = (
            "lunes",
            "martes",
            "miércoles",
            "jueves",
            "viernes",
            "sábado",
            "domingo",
        )
        months = (
            "enero",
            "febrero",
            "marzo",
            "abril",
            "mayo",
            "junio",
            "julio",
            "agosto",
            "septiembre",
            "octubre",
            "noviembre",
            "diciembre",
        )
        ticket_date = (
            f"{weekdays[parsed_date.weekday()]}, {parsed_date.day} de "
            f"{months[parsed_date.month - 1]} de {parsed_date.year}"
        )
        safe_date = escape(ticket_date)

        prize_names = (
            "PRIMERA",
            "SEGUNDA",
            "TERCERA",
            "CUARTA",
            "QUINTA",
            "SEXTA",
            "SEPTIMA",
        )
        prize_multipliers = (68, 10, 4, 2, 2, 1, 1)
        try:
            value = Decimal(str(ticket["ValorBoleto"]))
        except (KeyError, InvalidOperation, ValueError):
            value = Decimal("0")
        prizes_html = "".join(
            '<div class="prize-item"><span class="prize-name">'
            f"{name}</span><span class=\"prize-amount\">"
            f"${value * multiplier:.2f}</span></div>"
            for name, multiplier in zip(prize_names, prize_multipliers)
        )
        barcode_classes = (2, 1, 4, 1, 3, 5, 2, 1, 4, 3, 2, 5, 1, 4, 2, 3)
        barcode_html = "".join(
            f'<span class="b-{bar}"></span>' for bar in barcode_classes
        )

        return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Ticket Bonanza · {safe_number}</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      padding: 24px;
      display: flex;
      justify-content: center;
      align-items: flex-start;
      min-height: 100vh;
      background: #f8f9fa;
      color: #000;
      font-family: 'Courier New', Courier, monospace;
    }}
    .ticket-preview {{
      width: 100%;
      max-width: 300px;
      padding: 10px;
      background: #fff;
      box-shadow: 0 4px 10px rgba(0, 0, 0, .1);
      font-weight: 700;
      line-height: 1.2;
    }}
    .text-center {{ text-align: center; }}
    .text-right {{ text-align: right; }}
    .barcode-container {{
      display: flex;
      flex-direction: column;
      align-items: center;
      margin-bottom: 10px;
    }}
    .barcode {{ display: flex; align-items: flex-end; height: 45px; }}
    .barcode span {{ display: inline-block; height: 100%; background: #000; }}
    .b-1 {{ width: 2px; margin-right: 2px; }}
    .b-2 {{ width: 4px; margin-right: 1px; }}
    .b-3 {{ width: 1px; margin-right: 3px; }}
    .b-4 {{ width: 5px; margin-right: 2px; }}
    .b-5 {{ width: 3px; margin-right: 1px; }}
    .info-text {{ margin: 8px 0; font-size: 11px; }}
    .barcode-number {{
      margin-top: 4px;
      text-align: center;
      font-size: 12px;
      letter-spacing: 1px;
    }}
    .ticket-divider {{
      height: 0;
      margin: 8px 0;
      border-top: 2px dashed #000;
    }}
    .ticket-number {{
      margin: 10px 0 4px;
      text-align: center;
    }}
    .number-main {{ font-size: 28px; font-weight: 900; }}
    .code-middle {{
      margin: 7px 0;
      text-align: center;
      font-size: 12px;
      letter-spacing: 1px;
    }}
    .slogan {{ margin-bottom: 15px; }}
    .game-details {{ margin: 8px 0; font-size: 16px; }}
    .prizes {{ width: 100%; margin: 10px 0 0; }}
    .prize-item {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      align-items: center;
      column-gap: 12px;
      padding: 5px 0;
      font-size: 16px;
      line-height: 1.15;
    }}
    .prize-amount {{ min-width: 80px; text-align: right; font-weight: 900; }}
    .ticket-footer {{ text-align: center; font-size: 13px; font-weight: 900; }}
    .total-section {{ margin-top: 15px; font-size: 20px; font-weight: 900; }}
    @media print {{
      body {{ padding: 0; background: #fff; }}
      .ticket-preview {{
        width: 80mm;
        max-width: 80mm;
        padding: 3mm;
        box-shadow: none;
      }}
    }}
  </style>
</head>
<body>
  <main class="ticket-preview compact">
    <div class="barcode-container"><div class="barcode">{barcode_html}</div></div>
    <div class="info-text text-center">Generado: <span>{safe_date}</span></div>
    <div class="ticket-divider"></div>
    <div class="barcode-number"><span>{safe_code}</span></div>
    <div class="ticket-divider"></div>
    <div class="ticket-number number-main">NO#<span>{safe_number}</span></div>
    <div class="code-middle">AGENCIA: <span>{safe_agency}</span></div>
    <div class="thank-you slogan text-center"><br></div>
    <div class="game-details text-right">VALOR: $<span>{safe_value}</span></div>
    <div class="ticket-divider"></div>
    <div class="prizes">{prizes_html}</div>
    <div class="ticket-divider"></div>
    <footer class="ticket-footer">
      <div class="total-section text-right">TOTAL: $<span>{safe_value}</span></div>
    </footer>
  </main>
</body>
</html>"""
