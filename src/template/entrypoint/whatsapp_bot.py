"""Whatsapp Bot"""

import json
import logging
import os
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from template.adapters.database import SessionLocal, get_db
from template.adapters.repositories import (
    ChatSessionRepository,
    GroupRepository,
    MemberRepository,
    ProcessedMessageRepository,
    SQLAlchemyExpenseRepository,
)
from template.dependencies import get_processed_message_repository, get_whatsapp_client
from template.service_layer.expense_service import ExpenseService
from template.service_layer.member_service import MemberService
from template.service_layer.whatsapp_client import WhatsAppClient
from template.service_layer.whatsapp_service import (
    administrar_chatbot,
    mark_read_message,
    obtener_interactive_id_whatsapp,
    obtener_mensaje_whatsapp,
    replace_start,
)

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()


def _send_group_selector(number: str, message_id: str, groups: List[Any], wpp_client: WhatsAppClient) -> None:
    """Send an interactive group-selection message and mark the incoming message as read."""
    wpp_client.send_message(mark_read_message(message_id))
    rows = [{"id": f"grp_{g.id}", "title": g.name, "description": ""} for g in groups]
    msg = json.dumps(
        {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": number,
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {"text": "¿A qué grupo pertenece este gasto?"},
                "footer": {"text": "⚙️ Admin Gastos Compartidos ⚙️"},
                "action": {
                    "button": "Ver Grupos",
                    "sections": [{"title": "Mis Grupos", "rows": rows}],
                },
            },
        }
    )
    wpp_client.send_message(msg)


# pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-return-statements
def _resolve_group_id(
    number: str,
    message_id: str,
    interactive_id: Optional[str],
    estado: Dict[str, Any],
    groups: List[Any],
    wpp_client: WhatsAppClient,
) -> Optional[int]:
    """Return the group_id for this session, or None if the user must still pick a group.

    Precondition: caller has already verified the member exists and belongs to at least one group.
    Side effect: may send group-selector message via wpp_client and mutate estado.
    """
    if estado.get("group_id"):
        return int(estado["group_id"])

    if len(groups) == 1:
        estado["group_id"] = groups[0].id
        return groups[0].id

    # Multiple groups — selection required
    if estado.get("estado") == "esperando_seleccion_grupo":
        if interactive_id and interactive_id.startswith("grp_"):
            try:
                selected_id = int(interactive_id.split("_")[1])
                group = next((g for g in groups if g.id == selected_id), None)
                if group:
                    estado["group_id"] = group.id
                    estado["estado"] = "inicial"
                    return group.id
            except (ValueError, IndexError):
                pass
        # Invalid reply — re-prompt
        _send_group_selector(number, message_id, groups, wpp_client)
        return None

    # First message with multiple groups — prompt to select
    estado["estado"] = "esperando_seleccion_grupo"
    _send_group_selector(number, message_id, groups, wpp_client)
    return None


def _process_message(
    text: str,
    number: str,
    message_id: str,
    wpp_client: WhatsAppClient,
    interactive_id: str | None = None,
) -> None:
    """Run chatbot logic in a background task with its own DB session."""
    with SessionLocal() as db:
        session_repo = ChatSessionRepository(db)
        member_repo = MemberRepository(db)
        member_service = MemberService(member_repo)

        estado = session_repo.get_or_create(number)

        member = member_repo.get_member_by_phone(number)
        if not member:
            # Unknown phone: let administrar_chatbot send the registration prompt
            nuevo_estado = administrar_chatbot(
                text, number, message_id, estado, None, member_service, wpp_client, interactive_id
            )
            session_repo.save(number, nuevo_estado)
            return

        groups = GroupRepository(db).list_for_member(member.id)
        if not groups:
            # Registered member not yet assigned to any group
            wpp_client.send_message(
                json.dumps(
                    {
                        "messaging_product": "whatsapp",
                        "to": number,
                        "type": "text",
                        "text": {
                            "body": "⚠️ Tu cuenta aún no está en ningún grupo. " "Pedile a un admin que te agregue."
                        },
                    }
                )
            )
            return

        group_id = _resolve_group_id(number, message_id, interactive_id, estado, groups, wpp_client)
        if group_id is None:
            # Group selection prompt was sent; wait for user response
            session_repo.save(number, estado)
            return

        expense_service = ExpenseService(
            SQLAlchemyExpenseRepository(db),
            group_id=group_id,
            group_repo=GroupRepository(db),
        )

        nuevo_estado = administrar_chatbot(
            text, number, message_id, estado, expense_service, member_service, wpp_client, interactive_id
        )
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
        interactive_id = obtener_interactive_id_whatsapp(message)
    except (KeyError, IndexError, ValueError):
        return "ok"

    if not processed_repo.mark_if_new(message_id):
        logger.info("Duplicate message_id %s ignored", message_id)
        return "ok"

    background_tasks.add_task(_process_message, text, number, message_id, wpp_client, interactive_id)
    return "ok"
