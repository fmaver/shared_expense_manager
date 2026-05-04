"""Whatsapp Bot"""

import logging
import os

from dotenv import load_dotenv
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from template.adapters.database import SessionLocal, get_db
from template.adapters.repositories import ChatSessionRepository, ProcessedMessageRepository
from template.dependencies import (
    get_chat_session_repository,
    get_expense_service,
    get_member_service,
    get_processed_message_repository,
    get_whatsapp_client,
)
from template.service_layer.expense_service import ExpenseService
from template.service_layer.member_service import MemberService
from template.service_layer.whatsapp_client import WhatsAppClient
from template.service_layer.whatsapp_service import (
    administrar_chatbot,
    obtener_mensaje_whatsapp,
    replace_start,
)

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()


def _process_message(
    text: str,
    number: str,
    message_id: str,
    wpp_client: WhatsAppClient,
) -> None:
    """Run chatbot logic in a background task with its own DB session."""
    with SessionLocal() as db:
        session_repo = ChatSessionRepository(db)
        from template.adapters.repositories import MemberRepository, SQLAlchemyExpenseRepository

        expense_service = ExpenseService(SQLAlchemyExpenseRepository(db))
        member_service = MemberService(MemberRepository(db))

        estado = session_repo.get_or_create(number)
        nuevo_estado = administrar_chatbot(text, number, message_id, estado, expense_service, member_service, wpp_client)
        session_repo.save(number, nuevo_estado)


@router.get("/webhook", response_class=PlainTextResponse)
async def verificar_token(request: Request) -> str:
    """Verify token for webhook"""
    logger.info("Webhook verification attempt started")
    try:
        query_params = dict(request.query_params)
        token = query_params.get("hub.verify_token")
        challenge = query_params.get("hub.challenge")

        if token == os.getenv("TOKEN") and challenge:
            logger.info("Token verified successfully. Returning challenge: %s", challenge)
            return challenge

        logger.warning("Invalid token or missing challenge")
        raise HTTPException(status_code=403, detail="token incorrecto")
    except Exception as e:
        logger.error("Error verifying token: %s", str(e))
        raise HTTPException(status_code=403, detail=str(e)) from e


@router.post("/webhook", response_class=PlainTextResponse)
async def recibir_mensajes(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    wpp_client: WhatsAppClient = Depends(get_whatsapp_client),
    processed_repo: ProcessedMessageRepository = Depends(get_processed_message_repository),
) -> str:
    """Receive WhatsApp messages, ack immediately, process in background."""
    try:
        body = await request.json()
        entry = body["entry"][0]
        changes = entry["changes"][0]
        value = changes["value"]
        message = value["messages"][0]
        number = replace_start(message["from"])
        message_id = message["id"]
        text = obtener_mensaje_whatsapp(message)
    except (KeyError, IndexError, ValueError):
        # Not a user message (e.g. status update) — ack silently
        return "ok"

    # Deduplicate: if this message_id was already processed, ignore
    if not processed_repo.mark_if_new(message_id):
        logger.info("Duplicate message_id %s ignored", message_id)
        return "ok"

    background_tasks.add_task(_process_message, text, number, message_id, wpp_client)
    return "ok"
