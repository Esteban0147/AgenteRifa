from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlparse

import httpx


class BonanzaAPIError(RuntimeError):
    pass


class BonanzaTicketClient:
    def __init__(
        self,
        api_base_url: str,
        username: str,
        password: str,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        parsed_url = urlparse(api_base_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ValueError("BONANZA_API_BASE_URL debe ser una URL HTTP o HTTPS válida.")
        if not username or not password:
            raise ValueError("Configura BONANZA_API_USER y BONANZA_API_PASSWORD.")

        self._api_base_url = api_base_url.rstrip("/")
        self._username = username
        self._password = password
        self._http = http_client or httpx.AsyncClient(timeout=15.0)
        self._owns_http_client = http_client is None

    async def close(self) -> None:
        if self._owns_http_client:
            await self._http.aclose()

    async def _login(self) -> str:
        try:
            login_response = await self._http.post(
                f"{self._api_base_url}/login",
                json={"user": self._username, "password": self._password},
            )
        except httpx.RequestError as error:
            raise BonanzaAPIError("No se pudo conectar con el inicio de sesión de Bonanza.") from error

        login_data = self._read_json(login_response, "El inicio de sesión de Bonanza")
        token = login_data.get("token") if isinstance(login_data, dict) else None
        if not login_response.is_success or not isinstance(token, str) or not token:
            raise BonanzaAPIError(
                self._response_message(login_data, "Bonanza rechazó las credenciales configuradas.")
            )
        return token

    async def check_availability(self, number: str, ticket_value: Any) -> dict[str, Any]:
        if not isinstance(number, str) or len(number) != 2 or not number.isdigit():
            raise BonanzaAPIError("El número debe tener exactamente 2 cifras.")
        amount = self._validate_ticket_value(ticket_value)
        token = await self._login()

        try:
            response = await self._http.get(
                f"{self._api_base_url}/tickets/{number}/disponibilidad",
                headers={"Authorization": f"Bearer {token}"},
                params={"ValorBoleto": float(amount), "Cifra": 2},
            )
        except httpx.RequestError as error:
            raise BonanzaAPIError(
                "No se pudo consultar el cupo del número en Bonanza."
            ) from error

        data = self._read_json(response, "La consulta de disponibilidad de Bonanza")
        if not response.is_success:
            raise BonanzaAPIError(
                self._response_message(data, "Bonanza no pudo consultar el cupo del número.")
            )
        availability = data.get("data") if isinstance(data, dict) else None
        if (
            not isinstance(availability, dict)
            or availability.get("Numero") != number
            or not isinstance(availability.get("Disponible"), bool)
        ):
            raise BonanzaAPIError(
                "Bonanza respondió sin datos válidos de disponibilidad."
            )
        return availability

    async def create_ticket(self, number: str, ticket_value: Any) -> dict[str, Any]:
        if not isinstance(number, str) or len(number) != 2 or not number.isdigit():
            raise BonanzaAPIError("El boleto de Bonanza debe tener exactamente 2 cifras.")

        amount = self._validate_ticket_value(ticket_value)
        token = await self._login()

        try:
            ticket_response = await self._http.post(
                f"{self._api_base_url}/tickets",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "Numero": number,
                    "ValorBoleto": float(amount),
                    "Cifra": 2,
                    "TIPO": "Normal",
                    "Vendido": "open",
                },
            )
        except httpx.RequestError as error:
            raise BonanzaAPIError(
                "Se perdió la conexión durante la creación del boleto. "
                "Revisa Bonanza antes de volver a intentarlo para evitar duplicados."
            ) from error

        try:
            ticket_data = self._read_json(
                ticket_response, "La creación del boleto en Bonanza"
            )
        except BonanzaAPIError as error:
            raise BonanzaAPIError(
                f"{error} Revisa Bonanza antes de volver a intentarlo para evitar duplicados."
            ) from error
        if not ticket_response.is_success:
            raise BonanzaAPIError(
                self._response_message(ticket_data, "Bonanza no pudo crear el boleto.")
            )

        ticket = ticket_data.get("data") if isinstance(ticket_data, dict) else None
        if not isinstance(ticket, dict) or not ticket.get("IdTicket") or not ticket.get("codigo"):
            raise BonanzaAPIError(
                "Bonanza respondió sin los datos necesarios para confirmar el boleto; "
                "revisa el sistema antes de volver a intentarlo."
            )
        try:
            returned_value = Decimal(str(ticket.get("ValorBoleto")))
        except (InvalidOperation, ValueError):
            returned_value = Decimal("NaN")
        if (
            ticket.get("Numero") != number
            or returned_value != amount
            or ticket.get("Cifra") not in {2, "2"}
        ):
            raise BonanzaAPIError(
                "Bonanza creó un boleto con datos distintos a los solicitados; "
                "revisa el sistema antes de volver a intentarlo."
            )
        return ticket

    @staticmethod
    def _validate_ticket_value(ticket_value: Any) -> Decimal:
        try:
            amount = Decimal(str(ticket_value))
        except (InvalidOperation, ValueError):
            raise BonanzaAPIError("El valor del boleto no es válido.") from None
        if (
            not amount.is_finite()
            or amount < Decimal("0.50")
            or amount > Decimal("6.00")
            or amount * 2 != (amount * 2).to_integral_value()
        ):
            raise BonanzaAPIError(
                "El valor debe estar entre $0.50 y $6.00 en incrementos de $0.50."
            )
        return amount

    @staticmethod
    def _read_json(response: httpx.Response, operation: str) -> Any:
        try:
            return response.json()
        except ValueError as error:
            raise BonanzaAPIError(
                f"{operation} devolvió una respuesta que no es JSON."
            ) from error

    @staticmethod
    def _response_message(data: Any, fallback: str) -> str:
        if isinstance(data, dict):
            message = data.get("message") or data.get("error")
            if isinstance(message, str) and message.strip():
                return message
        return fallback
