from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from dotenv import dotenv_values, load_dotenv
from openai import AsyncOpenAI, OpenAIError
from pydantic import BaseModel, ConfigDict, Field

from app.agent import OpenAIAgent
from app.bonanza_api import BonanzaTicketClient
from app.simulated_tools import SimulatedRaffle

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)
WEB_DIR = Path(__file__).resolve().parent.parent / "web"
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(ENV_FILE)


def configured_openai_api_key() -> str | None:
    value = dotenv_values(ENV_FILE).get("OPENAI_API_KEY")
    return value.strip() if isinstance(value, str) and value.strip() else None


raffle = SimulatedRaffle()
agent: OpenAIAgent | None = None
client: AsyncOpenAI | None = None
ticket_client: BonanzaTicketClient | None = None


class SimulatedReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference: str = Field(min_length=1, max_length=80)
    amount: str = Field(min_length=1, max_length=20)
    date: str = Field(min_length=10, max_length=10)


class InboundMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_number: str = Field(min_length=1, max_length=40)
    text: str | None = Field(default=None, max_length=4000)
    image_attached: bool = False
    simulated_receipt: SimulatedReceipt | None = None


class OutboundMessage(BaseModel):
    from_number: str
    reply: str
    simulated: bool = True


class ResetConversation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_number: str = Field(min_length=1, max_length=40)


@asynccontextmanager
async def lifespan(_: FastAPI):
    global agent, client, ticket_client
    api_key = configured_openai_api_key()
    bonanza_user = os.getenv("BONANZA_API_USER")
    bonanza_password = os.getenv("BONANZA_API_PASSWORD")
    if bonanza_user and bonanza_password:
        ticket_client = BonanzaTicketClient(
            api_base_url=os.getenv(
                "BONANZA_API_BASE_URL", "http://127.0.0.1:3000/api"
            ),
            username=bonanza_user,
            password=bonanza_password,
        )
    else:
        logger.warning(
            "BONANZA_API_USER y/o BONANZA_API_PASSWORD no configurados; "
            "no se podrán crear boletos reales."
        )

    if api_key:
        client = AsyncOpenAI(api_key=api_key)
        agent = OpenAIAgent(
            client=client,
            model=os.getenv("OPENAI_MODEL", "gpt-6-luna"),
            raffle=raffle,
            ticket_client=ticket_client,
        )
    else:
        logger.warning("OPENAI_API_KEY no configurada; el endpoint de mensajes responderá 503.")
    yield
    if client is not None:
        await client.close()
    if ticket_client is not None:
        await ticket_client.close()


app = FastAPI(
    title="Agente de Rifa por WhatsApp (demo)",
    description=(
        "Chat y verificación bancaria simulados; creación de boletos mediante la API real de Bonanza."
    ),
    version="0.1.0",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")


@app.get("/", include_in_schema=False)
async def chat_page() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/conversations/reset")
async def reset_conversation(request: ResetConversation) -> dict[str, str]:
    raffle.reset_customer(request.from_number)
    if agent is not None:
        agent.reset(request.from_number)
    return {"status": "reset"}


@app.post("/webhook/whatsapp", response_model=OutboundMessage)
async def receive_whatsapp_message(message: InboundMessage) -> OutboundMessage:
    if agent is None:
        raise HTTPException(
            status_code=503,
            detail="Configura OPENAI_API_KEY para habilitar el agente.",
        )
    if message.simulated_receipt is not None and not message.image_attached:
        raise HTTPException(
            status_code=422,
            detail="simulated_receipt solo se acepta cuando image_attached es true.",
        )

    receipt: dict[str, str] | None = None
    if message.simulated_receipt is not None:
        receipt = message.simulated_receipt.model_dump()
    raffle.begin_message(message.from_number, receipt)
    try:
        reply = await agent.respond(
            message.from_number,
            message.text,
            message.image_attached,
        )
    except OpenAIError:
        logger.exception("La solicitud al servicio de OpenAI falló.")
        raise HTTPException(status_code=502, detail="No fue posible obtener respuesta de OpenAI.")
    except RuntimeError:
        logger.exception("El agente no pudo completar el turno.")
        raise HTTPException(status_code=502, detail="El agente no pudo completar la solicitud.")
    return OutboundMessage(from_number=message.from_number, reply=reply)


@app.get("/api/tickets/{ticket_id}.html")
async def get_ticket(ticket_id: str) -> Response:
    ticket_html: Any = raffle.ticket_html(ticket_id)
    if ticket_html is None:
        raise HTTPException(status_code=404, detail="Boleto no encontrado.")
    return Response(content=ticket_html, media_type="text/html")
