from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from openai import AsyncOpenAI

from app.bonanza_api import BonanzaAPIError, BonanzaTicketClient
from app.simulated_tools import SimulatedRaffle

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Eres un asistente amable de una rifa.
Habla siempre en español y en mensajes breves.
Solo se venden números de exactamente 2 cifras (00 a 99), con valores de $0.50 a
$6.00 en incrementos de $0.50. Pregunta el número y el valor elegidos y consulta
el cupo real en Bonanza mediante gestionar_numero_rifa antes de afirmar que el
número admite ese valor. Comunica el valor acumulado y cupo restante solo si la
herramienta responde correctamente. Esta consulta no aparta el número; acláralo
y advierte que el cupo puede cambiar hasta que Bonanza cree el boleto. El apartado
y los datos de pago son ficticios; explica claramente que nadie debe transferir dinero.
Si recibes un comprobante adjunto, ejecuta procesar_comprobante_ocr y luego
verificar_pago_banco. Nunca inventes ni cambies datos de OCR, pagos, referencias,
monto, fechas o confirmaciones. El banco simulado solo acepta comprobantes de
prueba cuyo monto sea exactamente igual al valor del boleto solicitado, en dólares;
eso no verifica un pago real y no debe presentarse como tal.
Solo informa que la validación de prueba se completó cuando la herramienta lo
confirme. Si el banco simulado lo rechaza, explica el motivo sin emitir boleto.
Para esta demostración, el banco simulado acepta una referencia que contenga la
palabra "pago" (sin distinguir mayúsculas/minúsculas), siempre que el monto
coincida exactamente con el precio del boleto. Aclara que este atajo solo sirve
para probar la demo.
Tras una validación de prueba completada, ejecuta enviar_ticket_whatsapp. Esa
herramienta crea el boleto REAL mediante la API de Bonanza; informa solo los datos
que devuelva la página y comparte su enlace. El enlace se muestra en este chat
simulado: no se envía ningún WhatsApp. Explica siempre que el boleto real se creó
después de una verificación de banco ficticia y que no se confirmó ningún pago real.
No solicites contraseñas, códigos de acceso ni información financiera sensible."""

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "gestionar_numero_rifa",
            "description": (
                "Consulta en Bonanza el cupo actual para el número de 2 cifras "
                "y el valor elegidos. Si hay cupo, registra la solicitud y genera "
                "una referencia de pago ficticia; no aparta el cupo."
            ),
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["reserve"]},
                    "number": {"type": "string"},
                    "ticket_value": {"type": "number"},
                },
                "required": ["action", "number", "ticket_value"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "procesar_comprobante_ocr",
            "description": "Extrae los datos de un comprobante de prueba adjunto al mensaje.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "verificar_pago_banco",
            "description": "Verifica el último comprobante contra el banco de prueba.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "enviar_ticket_whatsapp",
            "description": (
                "Crea el boleto en la API real de Bonanza tras validar el comprobante "
                "simulado y devuelve el enlace del boleto para el chat simulado."
            ),
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        },
    },
]


class OpenAIAgent:
    def __init__(
        self,
        client: AsyncOpenAI,
        model: str,
        raffle: SimulatedRaffle,
        ticket_client: BonanzaTicketClient | None = None,
    ) -> None:
        self._client = client
        self._model = model
        self._raffle = raffle
        self._ticket_client = ticket_client
        self._history: dict[str, list[dict[str, str]]] = {}
        self._ticket_locks: dict[str, asyncio.Lock] = {}

    def reset(self, user_id: str) -> None:
        self._history.pop(user_id, None)

    async def respond(
        self, user_id: str, text: str | None, has_image: bool
    ) -> str:
        user_message = (text or "").strip()
        if has_image:
            attachment_note = " [El cliente adjuntó un comprobante de prueba.]"
            user_message = f"{user_message}{attachment_note}".strip()
        if not user_message:
            user_message = " [El cliente envió un mensaje vacío.]"

        history = self._history.setdefault(user_id, [])
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            *history,
            {"role": "user", "content": user_message},
        ]

        for _ in range(6):
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                tools=TOOL_DEFINITIONS,
                tool_choice="auto",
                reasoning_effort="none",
            )
            assistant_message = response.choices[0].message
            if not assistant_message.tool_calls:
                answer = assistant_message.content or ""
                if not answer.strip():
                    raise RuntimeError("OpenAI devolvió una respuesta vacía.")
                history.extend(
                    [
                        {"role": "user", "content": user_message},
                        {"role": "assistant", "content": answer},
                    ]
                )
                self._history[user_id] = history[-20:]
                return answer

            messages.append(
                {
                    "role": "assistant",
                    "content": assistant_message.content,
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.function.name,
                                "arguments": call.function.arguments,
                            },
                        }
                        for call in assistant_message.tool_calls
                    ],
                }
            )
            for call in assistant_message.tool_calls:
                try:
                    arguments = json.loads(call.function.arguments)
                except json.JSONDecodeError:
                    logger.warning("OpenAI devolvió argumentos JSON inválidos para %s", call.function.name)
                    result = {"ok": False, "error": "Argumentos inválidos para la herramienta."}
                else:
                    result = await self._execute_tool(call.function.name, arguments, user_id)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )

        raise RuntimeError("OpenAI excedió el límite de llamadas a herramientas.")

    async def _execute_tool(
        self, name: str, arguments: dict[str, Any], user_id: str
    ) -> dict[str, Any]:
        if name == "gestionar_numero_rifa":
            if self._ticket_client is None:
                return {
                    "ok": False,
                    "error": (
                        "No se puede consultar el cupo: configura "
                        "BONANZA_API_USER y BONANZA_API_PASSWORD en el .env."
                    ),
                }
            if arguments.get("action") != "reserve":
                return {"ok": False, "error": "Acción no válida."}
            try:
                availability = await self._ticket_client.check_availability(
                    arguments.get("number"), arguments.get("ticket_value")
                )
            except BonanzaAPIError as error:
                logger.warning("No se pudo consultar el cupo en Bonanza: %s", error)
                return {"ok": False, "error": str(error)}
            if not availability["Disponible"]:
                return {
                    "ok": True,
                    "reserved": False,
                    "availability": availability,
                    "error": (
                        f"El número {availability['Numero']} no tiene cupo suficiente "
                        f"para el valor solicitado; quedan "
                        f"${availability.get('CupoRestante', 'desconocido')}."
                    ),
                }
            reservation = self._raffle.execute(name, arguments, user_id)
            if reservation.get("ok"):
                reservation["availability"] = availability
                reservation["reservation_is_simulated"] = True
            return reservation

        if name != "enviar_ticket_whatsapp":
            return self._raffle.execute(name, arguments, user_id)

        lock = self._ticket_locks.setdefault(user_id, asyncio.Lock())
        async with lock:
            result = self._raffle.execute(name, arguments, user_id)
            if not result.get("ready"):
                return result
            if self._ticket_client is None:
                return {
                    "ok": False,
                    "error": (
                        "La API de Bonanza no está configurada. Define "
                        "BONANZA_API_USER y BONANZA_API_PASSWORD en el .env y "
                        "reinicia el agente; no se creó ningún boleto."
                    ),
                }
            if not self._raffle.mark_ticket_creation_attempted(user_id):
                return {
                    "ok": False,
                    "error": (
                        "Ya se intentó crear el boleto de esta solicitud. Revisa "
                        "Bonanza antes de iniciar otra para evitar duplicados."
                    ),
                }
            try:
                ticket = await self._ticket_client.create_ticket(
                    result["number"], result["ticket_value"]
                )
            except BonanzaAPIError as error:
                logger.warning("No se pudo crear el boleto en Bonanza: %s", error)
                return {"ok": False, "error": str(error)}
            return self._raffle.record_ticket(user_id, ticket)
