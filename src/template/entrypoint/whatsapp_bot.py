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
    InvitationRepository,
    MemberRepository,
    ProcessedMessageRepository,
    RecurringGroupExpenseRepository,
    SQLAlchemyExpenseRepository,
)
from template.dependencies import get_processed_message_repository, get_whatsapp_client
from template.service_layer.expense_service import ExpenseService
from template.service_layer.member_service import MemberService
from template.service_layer.whatsapp_client import WhatsAppClient
from template.service_layer.whatsapp_service import (
    administrar_chatbot,
    group_selector_message,
    handle_image_expense,
    mark_read_message,
    obtener_interactive_id_whatsapp,
    obtener_mensaje_whatsapp,
    replace_start,
    text_message,
)

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()


def _send_group_selector(number: str, message_id: str, groups: List[Any], wpp_client: WhatsAppClient) -> None:
    """Send an interactive group-selection message and mark the incoming message as read."""
    wpp_client.send_message(mark_read_message(message_id))
    wpp_client.send_message(group_selector_message(number, groups))


# pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-return-statements
def _resolve_group_id(
    number: str,
    message_id: str,
    interactive_id: Optional[str],
    estado: Dict[str, Any],
    groups: List[Any],
    wpp_client: WhatsAppClient,
    text: str = "",
    image_media_id: str | None = None,
    image_mime_type: str = "image/jpeg",
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

    # First message with multiple groups — save text or image for replay, then prompt to select
    if image_media_id:
        estado["pending_image_media_id"] = image_media_id
        estado["pending_image_mime_type"] = image_mime_type
    else:
        estado["pending_quick_message"] = text
    estado["estado"] = "esperando_seleccion_grupo"
    _send_group_selector(number, message_id, groups, wpp_client)
    return None


def _handle_stub_claim(  # pylint: disable=too-many-locals
    text: str,
    number: str,
    message_id: str,
    member_id: int,
    estado: Dict[str, Any],
    db: Any,
    member_repo: MemberRepository,
    wpp_client: WhatsAppClient,
) -> Dict[str, Any]:
    """Handle the claim-confirmation flow for stub members (invited but not yet registered)."""
    wpp_client.send_message(mark_read_message(message_id))
    invitation_repo = InvitationRepository(db)
    state = estado.get("estado", "inicial")

    if state == "onboarding_claim_confirm":
        lowered = text.strip().lower()
        if lowered in ("si", "sí", "yes", "s"):
            member_repo.mark_phone_verified(member_id)
            invitation = invitation_repo.latest_pending_for_member(member_id)
            app_base_url = os.getenv("APP_BASE_URL", "http://localhost:5173")
            if invitation:
                claim_url = f"{app_base_url}/invite/{invitation.token}"
                body = (
                    f"✅ ¡Genial! Tu número fue confirmado.\n\n"
                    f"Para terminar de crear tu cuenta, abrí el siguiente enlace:\n{claim_url}"
                )
            else:
                # No pending invitation found — direct them to register
                body = (
                    "✅ ¡Genial! Tu número fue confirmado.\n\n"
                    f"Para crear tu cuenta, registrate en:\n{app_base_url}/register"
                )
            wpp_client.send_message(text_message(number, body))
            estado["estado"] = "inicial"
        elif lowered in ("no", "n"):
            wpp_client.send_message(text_message(number, "Entendido. Avisale a quien te invitó si hubo un error."))
            estado["estado"] = "inicial"
        else:
            wpp_client.send_message(
                text_message(number, "Por favor respondé *SI* para confirmar o *NO* si fue un error.")
            )
        return estado

    # First contact from a stub — send confirmation prompt
    invitation = invitation_repo.latest_pending_for_member(member_id)
    groups = GroupRepository(db).list_for_member(member_id)
    group_names = ", ".join(g.name for g in groups) if groups else "un grupo"
    inviter_name = invitation.inviter.name if invitation and invitation.inviter else "alguien"
    stub = member_repo.get(member_id)
    invitee_name = f", {stub.name}" if stub and stub.name else ""

    body = (
        f"👋 ¡Hola{invitee_name}! {inviter_name} te invitó al grupo *{group_names}*.\n\n"
        "¿Sos vos? Respondé *SI* para confirmar tu identidad o *NO* si fue un error."
    )
    wpp_client.send_message(text_message(number, body))
    estado["estado"] = "onboarding_claim_confirm"
    return estado


def _handle_group_invite_response(
    text: str,
    number: str,
    message_id: str,
    member: Any,
    estado: Dict[str, Any],
    invitation_repo: InvitationRepository,
    wpp_client: WhatsAppClient,
    db: Any,
) -> None:
    """Handle the SI/NO response when an existing member was asked to join a new group."""
    wpp_client.send_message(mark_read_message(message_id))
    lowered = text.strip().lower()
    pending_token = estado.get("pending_invitation_token")

    if lowered in ("si", "sí", "yes", "s"):
        inv = invitation_repo.get_by_token(pending_token) if pending_token else None
        if inv and inv.status.value == "pending":
            GroupRepository(db).add_member(inv.group_id, member.id)
            invitation_repo.mark_accepted(inv.id, member.id)
            wpp_client.send_message(text_message(number, "✅ ¡Te uniste al grupo! Decí _hola_ para ver el menú."))
        else:
            wpp_client.send_message(text_message(number, "La invitación ya no está disponible."))
    elif lowered in ("no", "n"):
        inv = invitation_repo.get_by_token(pending_token) if pending_token else None
        if inv:
            invitation_repo.revoke(inv.id)
        wpp_client.send_message(text_message(number, "Entendido. No te unirás al grupo."))
    else:
        wpp_client.send_message(text_message(number, "Por favor respondé *SI* para unirte o *NO* para rechazar."))
        return  # stay in the same state

    estado["estado"] = "inicial"
    estado.pop("pending_invitation_token", None)


def _process_image_message(  # pylint: disable=too-many-locals
    number: str,
    message_id: str,
    estado: Dict[str, Any],
    image_media_id: str,
    image_mime_type: str,
    expense_service: ExpenseService,
    member_service: MemberService,
    wpp_client: WhatsAppClient,
    session_repo: ChatSessionRepository,
) -> None:
    """Download an image and parse it as an expense, sending confirmation messages."""
    wpp_client.send_message(mark_read_message(message_id))
    try:
        image_bytes, resolved_mime = wpp_client.download_media(image_media_id)
        mime = resolved_mime or image_mime_type
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Failed to download image %s: %s", image_media_id, exc)
        wpp_client.send_message(
            text_message(number, "😕 No pude descargar la imagen. Intentá de nuevo o cargá el gasto manualmente.")
        )
        session_repo.save(number, estado)
        return
    responses, nuevo_estado = handle_image_expense(number, estado, image_bytes, mime, expense_service, member_service)
    for item in responses:
        wpp_client.send_message(item)
    session_repo.save(number, nuevo_estado)


def _process_message(  # pylint: disable=too-many-locals,too-many-return-statements
    text: str,
    number: str,
    message_id: str,
    wpp_client: WhatsAppClient,
    interactive_id: str | None = None,
    image_media_id: str | None = None,
    image_mime_type: str = "image/jpeg",
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
                text, number, message_id, estado, None, member_service, wpp_client, interactive_id, groups=[]
            )
            session_repo.save(number, nuevo_estado)
            return

        if member.is_stub:
            # Stub member — invitation claim flow only, not the full chatbot
            nuevo_estado = _handle_stub_claim(text, number, message_id, member.id, estado, db, member_repo, wpp_client)
            session_repo.save(number, nuevo_estado)
            return

        invitation_repo = InvitationRepository(db)

        # If waiting for a join-group response, handle it before anything else
        if estado.get("estado") == "esperando_respuesta_invitacion":
            _handle_group_invite_response(text, number, message_id, member, estado, invitation_repo, wpp_client, db)
            session_repo.save(number, estado)
            return

        # Prompt the user about any pending invitations to new groups
        pending_inv = invitation_repo.latest_pending_for_member(member.id)
        if pending_inv:
            group = GroupRepository(db).get(pending_inv.group_id)
            inviter = member_repo.get(pending_inv.inviter_id) if pending_inv.inviter_id else None
            group_name = group.name if group else "un grupo"
            inviter_name = inviter.name if inviter else "alguien"
            wpp_client.send_message(mark_read_message(message_id))
            wpp_client.send_message(
                text_message(
                    number,
                    f"👥 *{inviter_name}* te invitó al grupo *{group_name}*.\n\n"
                    "¿Querés unirte? Respondé *SI* para aceptar o *NO* para rechazar.",
                )
            )
            estado["estado"] = "esperando_respuesta_invitacion"
            estado["pending_invitation_token"] = pending_inv.token
            session_repo.save(number, estado)
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

        was_awaiting_group = estado.get("estado") == "esperando_seleccion_grupo"
        group_id = _resolve_group_id(
            number,
            message_id,
            interactive_id,
            estado,
            groups,
            wpp_client,
            text,
            image_media_id,
            image_mime_type,
        )
        if group_id is None:
            # Group selection prompt was sent; wait for user response
            session_repo.save(number, estado)
            return

        expense_service = ExpenseService(
            SQLAlchemyExpenseRepository(db),
            group_id=group_id,
            group_repo=GroupRepository(db),
        )
        recurring_repo = RecurringGroupExpenseRepository(db)

        # Group was just picked — replay a saved quick-expense message if present,
        # otherwise synthesise a greeting so the user lands on the main menu.
        if was_awaiting_group:
            pending_image = estado.pop("pending_image_media_id", None)
            pending_mime = estado.pop("pending_image_mime_type", "image/jpeg")
            if pending_image:
                image_media_id = pending_image
                image_mime_type = pending_mime
            else:
                text = estado.pop("pending_quick_message", None) or "hola"

        if image_media_id:
            # Image message: download and parse instead of going through the text chatbot
            _process_image_message(
                number,
                message_id,
                estado,
                image_media_id,
                image_mime_type,
                expense_service,
                member_service,
                wpp_client,
                session_repo,
            )
            return

        nuevo_estado = administrar_chatbot(
            text,
            number,
            message_id,
            estado,
            expense_service,
            member_service,
            wpp_client,
            interactive_id,
            groups=groups,
            recurring_repo=recurring_repo,
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
async def recibir_mensajes(  # pylint: disable=too-many-locals
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
        # Detect image messages
        image_media_id: str | None = None
        image_mime_type = "image/jpeg"
        if message.get("type") == "image":
            image_media_id = message["image"].get("id")
            image_mime_type = message["image"].get("mime_type", "image/jpeg")
    except (KeyError, IndexError, ValueError):
        return "ok"

    if not processed_repo.mark_if_new(message_id):
        logger.info("Duplicate message_id %s ignored", message_id)
        return "ok"

    background_tasks.add_task(
        _process_message,
        text,
        number,
        message_id,
        wpp_client,
        interactive_id,
        image_media_id,
        image_mime_type,
    )
    return "ok"
