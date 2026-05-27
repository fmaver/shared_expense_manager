# pylint: disable=too-many-lines
"""wpp service"""

import asyncio
import json
import os
import time
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

import requests

from template.domain.models.category import Category
from template.domain.models.enums import PaymentType
from template.domain.models.formatters import (
    format_amount_es,
    format_category_es,
    format_date_es,
    format_member_name_es,
    format_payment_type_es,
    month_name_es,
)
from template.domain.models.models import MonthlyShare
from template.domain.models.pdf_builder import ExpensePDF
from template.domain.schemas.expense import (
    CategorySchema,
    ExpenseCreate,
    SplitStrategySchema,
)
from template.service_layer.expense_service import ExpenseService
from template.service_layer.member_service import MemberService
from template.service_layer.quick_expense_parser import parse_quick_expense
from template.service_layer.whatsapp_client import WhatsAppClient


def obtener_mensaje_whatsapp(message: Dict[str, Any]) -> str:
    """get message"""
    if "type" not in message:
        text = "mensaje no reconocido"
        return text

    type_message = message["type"]
    if type_message == "text":
        text = message["text"]["body"]
    elif type_message == "button":
        text = message["button"]["text"]
    elif type_message == "interactive" and message["interactive"]["type"] == "list_reply":
        text = message["interactive"]["list_reply"]["title"]
    elif type_message == "interactive" and message["interactive"]["type"] == "button_reply":
        text = message["interactive"]["button_reply"]["title"]
    else:
        text = "mensaje no procesado"
    return text


def obtener_interactive_id_whatsapp(message: Dict[str, Any]) -> Optional[str]:
    """Return the interactive button/list reply ID, or None for plain text messages."""
    if message.get("type") == "interactive":
        interactive = message["interactive"]
        if interactive.get("type") == "button_reply":
            return interactive["button_reply"].get("id")
        if interactive.get("type") == "list_reply":
            return interactive["list_reply"].get("id")
    return None


def obtener_media_id(file_path: str) -> Tuple[str, int]:
    """get media id"""
    try:
        whatsapp_token = os.getenv("WHATSAPP_TOKEN")
        url = os.getenv("WHATSAPP_URL_MEDIA")

        if whatsapp_token is None:
            raise ValueError("WHATSAPP_TOKEN environment variable is not set")
        if url is None:
            raise ValueError("WHATSAPP_URL_MEDIA environment variable is not set")
        headers = {"Authorization": "Bearer " + whatsapp_token}

        with open(file_path, "rb") as file:
            files = {
                "file": (file_path, file, "application/pdf", {"Expires": "0"}),
            }
            upload_media = requests.post(
                url,
                data={
                    "messaging_product": "whatsapp",
                    "type": "application/pdf",
                },
                files=files,
                headers=headers,
                timeout=5,
            )
        if upload_media.status_code == 200:
            upload_media_data = upload_media.json()
            document_id = upload_media_data.get("id")
            print("document_id: ", document_id)
            return document_id, 200
        return "Error al enviar documento", upload_media.status_code
    except requests.exceptions.RequestException as e:
        return str(e), 403


def enviar_mensaje_whatsapp(data: str) -> Dict[str, Any]:
    """send message"""
    try:
        whatsapp_token = os.getenv("WHATSAPP_TOKEN")
        whatsapp_url = os.getenv("WHATSAPP_URL")

        if whatsapp_token is None:
            raise ValueError("WHATSAPP_TOKEN environment variable is not set")
        if whatsapp_url is None:
            raise ValueError("WHATSAPP_URL environment variable is not set")

        headers = {"Content-Type": "application/json", "Authorization": "Bearer " + whatsapp_token}
        print("se envia ", data)
        response = requests.post(whatsapp_url, headers=headers, data=data, timeout=5)
        print("WhatsApp API response:", response.status_code, response.text)

        if response.status_code == 200:
            return {"detail": "mensaje enviado", "status_code": 200}
        return {"detail": "error al enviar mensaje", "status_code": response.status_code}
    except ValueError as e:
        return {"detail": "no enviado, value error: " + str(e)}
    except requests.exceptions.RequestException as e:
        return {"detail": "no enviado " + str(e)}


def text_message(number: str, text: str) -> str:
    """text message"""
    data = json.dumps(
        {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": number,
            "type": "text",
            "text": {"body": text},
        }
    )
    return data


def template_message(number: str, template_name: str, language: str, parametes: List[Dict[str, Any]]) -> str:
    """template message"""
    data = json.dumps(
        {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": number,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language},
                "components": [{"type": "body", "parameters": parametes}],
            },
        }
    )
    return data


def button_reply_message(number: str, options: List[str], body: str, footer: str, sedd: str) -> str:
    """button reply message"""
    buttons = []
    for i, option in enumerate(options):
        buttons.append({"type": "reply", "reply": {"id": sedd + "_btn_" + str(i + 1), "title": option}})

    data = json.dumps(
        {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": number,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": body},
                "footer": {"text": footer},
                "action": {"buttons": buttons},
            },
        }
    )
    return data


def list_reply_message(number: str, options: List[str], body: str, footer: str, sedd: str) -> str:
    """list reply"""
    rows = []
    for i, option in enumerate(options):
        rows.append({"id": sedd + "_row_" + str(i + 1), "title": option, "description": ""})

    data = json.dumps(
        {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": number,
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {"text": body},
                "footer": {"text": footer},
                "action": {"button": "Ver Opciones", "sections": [{"title": "Secciones", "rows": rows}]},
            },
        }
    )
    return data


def member_select_message(number: str, options: List[str], body: str, footer: str, sedd: str) -> str:
    """Pick the right interactive payload based on option count.

    Meta caps interactive button replies at 3 options; for more, fall back to
    a list reply (capped at 10 rows).
    """
    if len(options) <= 3:
        return button_reply_message(number, options, body, footer, sedd)
    return list_reply_message(number, options, body, footer, sedd)


def group_selector_message(number: str, groups: List[Any]) -> str:
    """Build an interactive list for group selection (grp_<id> row IDs)."""
    rows = [{"id": f"grp_{g.id}", "title": g.name, "description": ""} for g in groups]
    return json.dumps(
        {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": number,
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {"text": "¿Qué grupo elegís?"},
                "footer": {"text": "⚙️ Admin Gastos Compartidos ⚙️"},
                "action": {"button": "Ver Grupos", "sections": [{"title": "Mis Grupos", "rows": rows}]},
            },
        }
    )


def notification_message_with_buttons(number: str, body: str, app_url: str) -> str:
    """Interactive notification with app URL in body and 'Entendido' quick reply button.

    Used for expense created/updated/deleted notifications within the 24h window.
    Replicates the template UX (visit-site link + acknowledge button) for free-form messages.
    """
    return json.dumps(
        {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": number,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": f"{body}\n\n🔗 {app_url}"},
                "footer": {"text": "⚙️ Jirens Shared Expenses"},
                "action": {"buttons": [{"type": "reply", "reply": {"id": "notif_ok", "title": "✅ Entendido"}}]},
            },
        }
    )


def category_select_message(number: str) -> str:
    """Build a list_reply with cat_<name> IDs for category selection."""
    categories = Category.get_numbered_categories_with_emoji()
    rows = [
        {"id": f"cat_{name}", "title": f"{name.capitalize()} {emoji}", "description": ""}
        for _, name, emoji in categories
    ]
    data = json.dumps(
        {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": number,
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {"text": "🏷️ ¿Cuál es la categoría del gasto?"},
                "footer": {"text": "⚙️ Admin Gastos Compartidos ⚙️"},
                "action": {"button": "Ver Categorías", "sections": [{"title": "Categorías", "rows": rows}]},
            },
        }
    )
    return data


def document_message(number: str, media_id: str, caption: str, filename: str) -> str:
    """document message"""
    data = json.dumps(
        {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": number,
            "type": "document",
            "document": {"id": media_id, "caption": caption, "filename": filename},
        }
    )
    return data


def image_message(url: str) -> str:
    """image message"""
    data = json.dumps(
        {"messaging_product": "whatsapp", "recipient_type": "individual", "type": "image", "image": {"link": url}}
    )
    return data


def sticker_message(number: str, sticker_id: str) -> str:
    """sticker message"""
    data = json.dumps(
        {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": number,
            "type": "sticker",
            "sticker": {"id": sticker_id},
        }
    )
    return data


def reply_reaction_message(number: str, message_id: str, emoji: str) -> str:
    """reply with reaction"""
    data = json.dumps(
        {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": number,
            "type": "reaction",
            "reaction": {"message_id": message_id, "emoji": emoji},
        }
    )
    return data


def reply_text_message(number: str, message_id: str, text: str) -> str:
    """reply text"""
    data = json.dumps(
        {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": number,
            "context": {"message_id": message_id},
            "type": "text",
            "text": {"body": text},
        }
    )
    return data


def mark_read_message(message_id: str) -> str:
    """clavar visto"""
    data = json.dumps({"messaging_product": "whatsapp", "status": "read", "message_id": message_id})
    return data


def update_member_last_chat(number: str, member_service: MemberService) -> None:
    """Update member's last WhatsApp chat datetime if member exists."""
    member = member_service.get_member_by_phone(number)
    if member:
        member_service.update_last_wpp_chat(number)
    else:
        print(f"Member with phone {number} not found")


def handle_cancel(
    number: str,
    estado_actual_usuario: Dict[str, Any],
    member_service: MemberService,
    groups: Optional[List[Any]] = None,
) -> Tuple[List[str], Dict[str, Any]]:
    """Abort any in-progress flow and return user to the main menu."""
    estado_actual_usuario = clean_estado_usuario(estado_actual_usuario)
    responses, estado_actual_usuario = handle_greetings(number, estado_actual_usuario, member_service, groups)
    cancel_notice = text_message(number, "❌ Operación cancelada.")
    return [cancel_notice] + responses, estado_actual_usuario


# pylint: disable=too-many-branches, too-many-statements
# flake8: noqa: C901
# pylint: disable=too-many-arguments
# pylint: disable=too-many-positional-arguments
def administrar_chatbot(
    text: str,
    number: str,
    message_id: str,
    estado_actual_usuario: Dict[str, Any],
    service: Optional[ExpenseService],
    member_service: MemberService,
    wpp_client: "WhatsAppClient",
    interactive_id: Optional[str] = None,
    groups: Optional[List[Any]] = None,
) -> Dict[str, Any]:  # noqa: C901
    """logica del bot"""
    groups = groups or []
    user_responses = []
    print("mensaje del usuario: ", text)
    print("estado actual del usuario: ", estado_actual_usuario["estado"])

    mark_read = mark_read_message(message_id)
    user_responses.append(mark_read)
    time.sleep(1)

    if "cancelar" in text.lower():
        update_member_last_chat(number, member_service)
        responses, estado_actual_usuario = handle_cancel(number, estado_actual_usuario, member_service, groups)
        user_responses.extend(responses)

    elif "cambiar grupo" in text.lower():
        update_member_last_chat(number, member_service)
        responses, estado_actual_usuario = handle_cambiar_grupo(number, estado_actual_usuario, groups)
        user_responses.extend(responses)

    elif "hola" in text.lower() or "inicio" in text.lower() or "entendido" in text.lower():
        update_member_last_chat(number, member_service)
        responses, estado_actual_usuario = handle_greetings(number, estado_actual_usuario, member_service, groups)
        user_responses.extend(responses)

    elif "no gracias" in text.lower():
        # Update last WhatsApp chat datetime at the start of any interaction
        update_member_last_chat(number, member_service)
        responses, estado_actual_usuario = handle_no_thanks(number, estado_actual_usuario, message_id)
        user_responses.extend(responses)

    elif "obtener documento" in text.lower():
        responses, estado_actual_usuario = handle_document_request(number, estado_actual_usuario, service, wpp_client)
        user_responses.extend(responses)

    elif "generar balance" in text.lower():
        responses, estado_actual_usuario = handle_balance_request(number, estado_actual_usuario, message_id)
        user_responses.extend(responses)

    elif "saldar cuentas" in text.lower():
        responses, estado_actual_usuario = send_acknowledgement_settle_accounts(number, estado_actual_usuario)
        user_responses.extend(responses)

    elif estado_actual_usuario["estado"] == "esperando_confirmacion_saldar_cuentas":
        responses, estado_actual_usuario = handle_settle_accounts(
            number, estado_actual_usuario, message_id, service, text
        )
        user_responses.extend(responses)

    elif estado_actual_usuario["estado"] == "esperando_fecha_balance":
        responses, estado_actual_usuario = handle_waiting_for_balance_date(number, estado_actual_usuario, text, service)
        user_responses.extend(responses)

    elif "prestar plata" in text.lower():
        responses, estado_actual_usuario = handle_lending_money(number, estado_actual_usuario, message_id)
        user_responses.extend(responses)

    elif "cargar gasto" in text.lower():
        responses, estado_actual_usuario = handle_loading_expense(number, estado_actual_usuario, message_id)
        user_responses.extend(responses)

    elif estado_actual_usuario["estado"] == "esperando_monto":
        responses, estado_actual_usuario = handle_waiting_for_amount(number, estado_actual_usuario, message_id, text)
        user_responses.extend(responses)

    elif estado_actual_usuario["estado"] == "esperando_descripcion":
        responses, estado_actual_usuario = handle_waiting_for_description(number, estado_actual_usuario, text, service)
        user_responses.extend(responses)

    elif estado_actual_usuario["estado"] == "esperando_pagador":
        responses, estado_actual_usuario = handle_waiting_for_payer(
            number, estado_actual_usuario, message_id, text, member_service
        )
        user_responses.extend(responses)

    elif estado_actual_usuario["estado"] == "esperando_fecha_pago":
        responses, estado_actual_usuario = handle_waiting_for_payment_date(
            number, estado_actual_usuario, text, member_service, message_id
        )
        user_responses.extend(responses)

    elif estado_actual_usuario["estado"] == "esperando_destinatario_prestamo":
        responses, estado_actual_usuario = handle_waiting_for_loan_recipient(
            number, estado_actual_usuario, text, member_service
        )
        user_responses.extend(responses)

    elif estado_actual_usuario["estado"] == "esperando_categoria":
        responses, estado_actual_usuario = handle_waiting_for_category(
            number, estado_actual_usuario, text, message_id, interactive_id
        )
        user_responses.extend(responses)

    elif estado_actual_usuario["estado"] == "esperando_tipo_pago":
        responses, estado_actual_usuario = handle_waiting_for_payment_type(
            number, estado_actual_usuario, message_id, text
        )
        user_responses.extend(responses)

    elif estado_actual_usuario["estado"] == "esperando_cuotas":
        responses, estado_actual_usuario = handle_waiting_for_installments(number, estado_actual_usuario, text)
        user_responses.extend(responses)

    elif estado_actual_usuario["estado"] == "esperando_estrategia":
        responses, estado_actual_usuario = handle_waiting_for_split_strategy(
            number, estado_actual_usuario, message_id, text, member_service, interactive_id, service
        )
        user_responses.extend(responses)

    elif estado_actual_usuario["estado"] == "esperando_definicion_participantes":
        responses, estado_actual_usuario = handle_waiting_for_participants_definition(
            number, estado_actual_usuario, text, member_service, interactive_id, service
        )
        user_responses.extend(responses)

    elif estado_actual_usuario["estado"] == "esperando_excluidos":
        responses, estado_actual_usuario = handle_waiting_for_excluded_members(
            number, estado_actual_usuario, member_service, interactive_id, service
        )
        user_responses.extend(responses)

    elif estado_actual_usuario["estado"] == "esperando_monto_para_miembro":
        responses, estado_actual_usuario = handle_waiting_for_amount_for_member(
            number, estado_actual_usuario, text, message_id, member_service, service
        )
        user_responses.extend(responses)

    elif estado_actual_usuario["estado"] == "esperando_porcentaje":
        responses, estado_actual_usuario = handle_waiting_for_percentage(
            number, estado_actual_usuario, text, member_service, service
        )
        user_responses.extend(responses)

    elif estado_actual_usuario["estado"] == "esperando_porcentaje_para_miembro":
        responses, estado_actual_usuario = handle_waiting_for_percentage_for_member(
            number, estado_actual_usuario, text, message_id, member_service, service
        )
        user_responses.extend(responses)

    elif estado_actual_usuario["estado"] == "esperando_confirmacion":
        update_member_last_chat(number, member_service)
        responses, estado_actual_usuario = handle_waiting_for_confirmation(
            number, estado_actual_usuario, text, service, member_service
        )
        user_responses.extend(responses)

    elif estado_actual_usuario["estado"] == "esperando_confirmacion_duplicado":
        update_member_last_chat(number, member_service)
        responses, estado_actual_usuario = handle_waiting_for_duplicate_confirmation(
            number, estado_actual_usuario, text, service, member_service, interactive_id
        )
        user_responses.extend(responses)

    elif estado_actual_usuario["estado"] == "esperando_respuesta_mes_saldado":
        update_member_last_chat(number, member_service)
        responses, estado_actual_usuario = handle_waiting_for_settled_response(
            number, estado_actual_usuario, text, service, member_service, interactive_id
        )
        user_responses.extend(responses)

    elif estado_actual_usuario["estado"] == "esperando_fecha_gasto_saldado":
        update_member_last_chat(number, member_service)
        responses, estado_actual_usuario = handle_waiting_for_settled_date(
            number, estado_actual_usuario, text, service, member_service
        )
        user_responses.extend(responses)

    elif estado_actual_usuario["estado"] == "inicial":
        update_member_last_chat(number, member_service)
        responses, estado_actual_usuario = handle_quick_expense(
            number, estado_actual_usuario, text, service, member_service
        )
        user_responses.extend(responses)

    else:
        update_member_last_chat(number, member_service)
        data = text_message(number, "Lo siento, no entendí lo que dijiste.")
        user_responses.append(data)

    for item in user_responses:
        print("enviando...", item)
        wpp_client.send_message(item)

    return estado_actual_usuario  # noqa: C901


def create_expense(
    number: str,
    estado_actual_usuario: Dict[str, Any],
    service: ExpenseService,
    split_strategy_dict: Dict[str, Any],
    member_service: MemberService,
):
    """create expense"""
    payment_type = (
        PaymentType.CREDIT
        if estado_actual_usuario["expense_data"]["payment_type"] in ("credito", "crédito")
        else PaymentType.DEBIT
    )
    expense_data = ExpenseCreate(
        description=estado_actual_usuario["expense_data"]["description"],
        amount=estado_actual_usuario["expense_data"]["amount"],
        date=estado_actual_usuario["expense_data"]["date"],
        category=CategorySchema(name=estado_actual_usuario["expense_data"]["category"]),
        payer_id=estado_actual_usuario["expense_data"]["payer_id"],
        payment_type=payment_type,
        installments=estado_actual_usuario["expense_data"]["installments"],
        split_strategy=SplitStrategySchema(**split_strategy_dict),
    )
    expense = service.create_expense(expense_data)

    # Get all members to notify
    members = service.get_members()
    group_name = service.get_group_name()
    multi_group_ids = service.get_multi_group_member_ids(members)

    # Get creator member by phone number
    member_creator = member_service.get_member_by_phone(number)

    # Send notifications asynchronously
    if member_creator:
        print("the member creator is: ", member_creator.name)
        # pylint: disable=C0415  # Import outside toplevel
        from template.service_layer.notification_service import NotificationService

        notification_service = NotificationService()
        asyncio.run(
            notification_service.notify_expense_created(
                expense,
                members,
                member_creator,
                member_service,
                group_name=group_name,
                multi_group_member_ids=multi_group_ids,
            )
        )


# al parecer para Argentina, whatsapp agrega 549 como prefijo en lugar de 54,
# este codigo soluciona ese inconveniente.
def replace_start(s: str) -> str:
    """replace starting number"""
    number = s[3:]
    if s.startswith("521"):
        return "52" + number
    if s.startswith("549"):
        return "54" + number
    return s


def clean_estado_usuario(estado_actual_usuario: Dict[str, Any]) -> Dict[str, Any]:
    """clean user state"""
    estado_actual_usuario["estado"] = "inicial"
    estado_actual_usuario["expense_data"] = {
        "service": None,
        "description": None,
        "amount": None,
        "date": None,
        "category": None,
        "payer_id": None,
        "payment_type": None,
        "installments": 1,
        "split_strategy": None,
    }
    # Defensively clear any in-progress queue state
    for key in (
        "remaining_member_ids",
        "pending_percentages",
        "pending_amounts",
        "excluded_member_ids",
        "all_member_ids",
    ):
        estado_actual_usuario["expense_data"].pop(key, None)
    return estado_actual_usuario


def handle_greetings(  # pylint: disable=too-many-locals
    number: str,
    estado_actual_usuario: Dict[str, Any],
    member_service: MemberService,
    groups: Optional[List[Any]] = None,
) -> Tuple[List[str], Dict[str, Any]]:
    """handle greetings"""
    user_responses = []

    print(f"Validating number: {number}")
    member_name = member_service.get_member_name_by_phone(number)

    if not member_name:
        body = """👋 ¡Hola! Tu número no está registrado en Jirens Shared Expenses.
\n\nPara poder utilizar el servicio, por favor regístrate en:\nhttps://shared-expense-front.onrender.com/"""
        response = text_message(number, body)
        user_responses.append(response)
        return user_responses, estado_actual_usuario

    # Resolve active group name for the greeting line
    groups = groups or []
    active_group_id = estado_actual_usuario.get("group_id")
    active_group_name: Optional[str] = None
    if active_group_id:
        active_group_name = next((g.name for g in groups if g.id == int(active_group_id)), None)
    if active_group_name is None and len(groups) == 1:
        active_group_name = groups[0].name

    group_line = f"\n\n📋 Grupo activo: *{active_group_name}*" if active_group_name else ""
    body = (
        f"👋 ¡Hola {member_name}! Bienvenido a Jirens Shared Expenses ✨{group_line}\n"
        "¿Cómo podemos ayudarte hoy?\n\n"
        "💡 Podés escribir _cancelar_ en cualquier momento para volver al inicio.\n"
        "⚡ Escribí directamente, ej: _gasté $500 en el super_\n"
        "📷 O enviá una foto del comprobante o ticket"
    )
    footer = "⚙️ Admin Gastos Compartidos ⚙️"
    options = ["💰 Cargar Gasto", "💸 Prestar Plata", "📊 Generar Balance"]
    if len(groups) > 1:
        options.append("🔄 Cambiar Grupo")

    # member_select_message auto-picks button (≤3) or list (>3)
    user_responses.append(member_select_message(number, options, body, footer, "sed1"))

    # Detect groups the user joined since their last greeting
    known_ids: set = set(estado_actual_usuario.get("known_group_ids", []))
    current_ids = {g.id for g in groups}
    new_groups = [g for g in groups if g.id not in known_ids and known_ids]
    if new_groups:
        new_names = ", ".join(f"*{g.name}*" for g in new_groups)
        user_responses.append(
            text_message(number, f"💡 Te uniste a un nuevo grupo: {new_names}. Decí _cambiar grupo_ para cambiarte.")
        )

    estado_actual_usuario = clean_estado_usuario(estado_actual_usuario)
    estado_actual_usuario["known_group_ids"] = list(current_ids)

    return user_responses, estado_actual_usuario


def handle_cambiar_grupo(
    number: str,
    estado_actual_usuario: Dict[str, Any],
    groups: List[Any],
) -> Tuple[List[str], Dict[str, Any]]:
    """Clear the active group and prompt the user to pick a new one."""
    estado_actual_usuario.pop("group_id", None)
    estado_actual_usuario["estado"] = "esperando_seleccion_grupo"
    return [group_selector_message(number, groups)], estado_actual_usuario


def handle_document_request(  # pylint: disable=too-many-locals
    number: str, estado_actual_usuario: Dict[str, Any], service: ExpenseService, wpp_client: "WhatsAppClient"
) -> Tuple[List[str], Dict[str, Any]]:
    """handle document"""
    user_responses = []

    fecha = estado_actual_usuario["expense_data"]["date"]
    month_year = datetime.strptime(fecha, "%m-%Y")
    print("calculando balance para el mes y año: ", month_year.month, month_year.year)

    monthly_share = service.get_monthly_balance(month_year.year, month_year.month)
    monthly_balance_dict = monthly_share.balances if monthly_share else {}  # Dict[str, float]
    is_settled = bool(monthly_share and monthly_share.is_settled)
    print("monthly_balance_dict: ", monthly_balance_dict)
    monthly_expenses_list = service.get_monthly_expenses(month_year.year, month_year.month)

    print("instanciando el generador de PDF...")
    filename = f"balance_{month_year.month}_{month_year.year}.pdf"

    # Generar el PDF, utilizando como ruta de almacenamiento la variable de entorno STORAGE_PATH
    pdf_generator = ExpensePDF(storage_path=os.getenv("STORAGE_PATH", "/tmp/storage"))

    member_names_dict = service.get_member_names()  # Obtener nombres de miembros
    file_path = pdf_generator.generate_expense_report(
        monthly_expenses_list, monthly_balance_dict, filename, member_names_dict, is_settled=is_settled
    )
    print(f"Archivo PDF generado en: {file_path}")

    media_id = wpp_client.upload_media(file_path)[0]

    member_names = ", ".join(member_names_dict.values()) or "todos los miembros"
    caption = f"📑 Balance de {member_names} para {month_year.month}/{month_year.year}"

    document_data = document_message(number, media_id, caption, filename)
    user_responses.append(document_data)
    print("enviando documento...")

    options = ["💰 Cargar Gasto", "💸 Prestar Plata", "📊 Generar Balance"]
    footer = "⚙️ Admin Gastos Compartidos ⚙️"
    follow_up = button_reply_message(number, options, "¿Querés hacer algo más?", footer, "sed1")
    user_responses.append(follow_up)
    estado_actual_usuario = clean_estado_usuario(estado_actual_usuario)

    return user_responses, estado_actual_usuario


def handle_balance_request(
    number: str, estado_actual_usuario: Dict[str, Any], message_id: str
) -> Tuple[List[str], Dict[str, Any]]:
    """handle balance"""
    user_responses = []

    estado_actual_usuario["expense_data"]["service"] = "generar balance"

    body = """📊 ¿De qué mes quieres ver el balance?\n
Por favor, ingresa el mes y año en el formato:\nMM-AAAA\n
✨ Ejemplo: 01-2025"""
    reply_text = reply_text_message(number, message_id, body)
    user_responses.append(reply_text)

    estado_actual_usuario["estado"] = "esperando_fecha_balance"

    return user_responses, estado_actual_usuario


def send_acknowledgement_settle_accounts(
    number: str, estado_actual_usuario: Dict[str, Any]
) -> Tuple[List[str], Dict[str, Any]]:
    """send acknowledge settle accounts"""
    user_responses = []

    fecha = estado_actual_usuario["expense_data"]["date"]

    body = f"⚠️ Estás a punto de saldar las cuentas para el mes y año: {fecha}.\n¿Estás seguro?"
    footer = "⚠️ Este proceso es irreversible"
    options = ["✅ Sí", "❌ No"]

    reply_button_data = button_reply_message(number, options, body, footer, "sed1")
    user_responses.append(reply_button_data)

    estado_actual_usuario["estado"] = "esperando_confirmacion_saldar_cuentas"

    return user_responses, estado_actual_usuario


def handle_settle_accounts(
    number: str, estado_actual_usuario: Dict[str, Any], message_id: str, service: ExpenseService, text: str
) -> Tuple[List[str], Dict[str, Any]]:
    """handle settle shares"""
    user_responses = []

    if text.lower() == "no":
        body = "👍 ¡De acuerdo! ¿Podemos ayudarte con algo más?"
        options = ["🏠 Ir al Inicio", "👋 No gracias"]
        footer = "⚙️ Admin Gastos Compartidos ⚙️"

        reply_button_data = button_reply_message(number, options, body, footer, "sed1")
        user_responses.append(reply_button_data)

        return user_responses, estado_actual_usuario

    fecha = estado_actual_usuario["expense_data"]["date"]
    month_year = datetime.strptime(fecha, "%m-%Y")
    print("saldando cuentas para el mes y año: ", str(month_year.month), str(month_year.year))

    monthly_share_settled = service.settle_monthly_share(month_year.year, month_year.month)
    print(f"monthly_share_settled with balance: {monthly_share_settled.balances}")

    # Llamar al método settle_monthly_share del servicio
    try:
        body = """✨ ¡Cuentas saldadas!\n\n¿Te gustaría hacer algo más? 🤔"""
        options = ["🏠 Ir al Inicio", "👋 No gracias", "📄 Obtener Documento"]
        footer = "⚙️ Admin Gastos Compartidos ⚙️"

        reply_button_data = button_reply_message(number, options, body, footer, "sed1")
        user_responses.append(reply_button_data)

    except ValueError as e:
        print("Error al saldar cuentas: ", e)
        body = str(e)
        reply_text = reply_text_message(number, message_id, body)
        user_responses.append(reply_text)

    return user_responses, estado_actual_usuario


def handle_waiting_for_balance_date(
    number: str, estado_actual_usuario: Dict[str, Any], text: str, service: ExpenseService
) -> Tuple[List[str], Dict[str, Any]]:
    """handle waiting for payment date"""
    user_responses = []

    def process_balance(month_year: datetime) -> MonthlyShare:
        monthly_balance = service.get_monthly_balance(month_year.year, month_year.month)
        if isinstance(monthly_balance, MonthlyShare):
            return monthly_balance
        return None

    def generate_balance_message(monthly_balance: MonthlyShare, month_year: datetime) -> str:
        balances_message = f"Balances de gastos para {month_year.month}/{month_year.year}:\n\n"
        member_names_dict = service.get_member_names()  # Obtener nombres de miembros
        for member_id, balance in monthly_balance.balances.items():
            member_name = member_names_dict.get(int(member_id), "Desconocido")
            if balance > 0:
                balances_message += f"🤑 {member_name} debe recibir ${balance}\n"
            elif balance < 0:
                balances_message += f"🥵 {member_name} debe pagar ${-balance}\n"
            else:
                balances_message += f"🙂 {member_name} estas al dia\n"
        return balances_message

    try:
        month_year = datetime.strptime(text.lower(), "%m-%Y")
        estado_actual_usuario["expense_data"]["date"] = text.lower()

        print("calculando balance para el mes y año: ", month_year.month, month_year.year)

        monthly_balance = process_balance(month_year)
        if monthly_balance:
            body = generate_balance_message(monthly_balance, month_year)
            options = ["📄 Obtener Documento", "💰 Saldar Cuentas", "🏠 Ir al Inicio"]
            reply_button_data = button_reply_message(number, options, body, "⚙️ Admin Gastos Compartidos ⚙️", "sed1")
            user_responses.append(reply_button_data)
        else:
            user_responses.append(text_message(number, "No se encontraron gastos para el mes y año seleccionados."))

        return user_responses, estado_actual_usuario

    except ValueError:
        user_responses.append(
            text_message(number, "El formato ingresado no es válido. Por favor, intenta de nuevo con\nMM-AAAA.")
        )
        return user_responses, estado_actual_usuario


def handle_lending_money(
    number: str, estado_actual_usuario: Dict[str, Any], message_id: str
) -> Tuple[List[str], Dict[str, Any]]:
    """handle lend money"""
    user_responses = []

    estado_actual_usuario["expense_data"]["service"] = "prestar plata"

    body = """💸 ¿Cuánto dinero deseas prestar?\n\nPor favor, ingresa el monto sin símbolos\n
✨ Ejemplo: 1234,56"""
    reply_text = reply_text_message(number, message_id, body)
    user_responses.append(reply_text)

    estado_actual_usuario["estado"] = "esperando_monto"

    return user_responses, estado_actual_usuario


def handle_loading_expense(
    number: str, estado_actual_usuario: Dict[str, Any], message_id: str
) -> Tuple[List[str], Dict[str, Any]]:
    """handle loading expense"""
    user_responses = []

    estado_actual_usuario["expense_data"]["service"] = "cargar gasto"

    body = """💰 ¿Cuál es el monto del gasto?\n\nPor favor, ingresa el valor sin símbolos\n
✨ Ejemplo: 1234,56"""
    reply_text = reply_text_message(number, message_id, body)
    user_responses.append(reply_text)

    estado_actual_usuario["estado"] = "esperando_monto"

    return user_responses, estado_actual_usuario


def handle_waiting_for_amount(
    number: str, estado_actual_usuario: Dict[str, Any], message_id: str, text: str
) -> Tuple[List[str], Dict[str, Any]]:
    """handle waiting for amount"""
    user_responses = []
    print("esperando_monto")
    try:
        amount = float(text.strip().replace(",", "."))
        estado_actual_usuario["expense_data"]["amount"] = amount

        body = "🖊️ ¿Cuál es el motivo del gasto?\n\nPor favor, escribe una breve descripción 📝"
        reply_text = reply_text_message(number, message_id, body)
        user_responses.append(reply_text)

        estado_actual_usuario["estado"] = "esperando_descripcion"

    except ValueError:
        error_message = text_message(
            number,
            "❌ El monto ingresado no es válido. Por favor, intenta de nuevo.\n"
            "(podés usar punto o coma para los decimales, ej: 1234,56)",
        )
        user_responses.append(error_message)

    return user_responses, estado_actual_usuario


def handle_waiting_for_description(
    number: str, estado_actual_usuario: Dict[str, Any], text: str, expense_service: ExpenseService
) -> Tuple[List[str], Dict[str, Any]]:
    """handle wiaitng for desc"""
    user_responses = []
    if estado_actual_usuario["expense_data"]["service"] == "cargar gasto":
        estado_actual_usuario["expense_data"]["description"] = text.lower()
        body = "👤 ¿Quién realizó el gasto?\n\nSelecciona la persona que pagó ⬇️"
    else:
        estado_actual_usuario["expense_data"]["description"] = f"{text.lower()}"
        body = "👤 ¿Quién realizó el préstamo?\n\nSelecciona la persona que prestó el dinero ⬇️"

    footer = "⚙️ Admin Gastos Compartidos ⚙️"
    members_dict = expense_service.get_member_names()
    options = list(members_dict.values())

    estado_actual_usuario["estado"] = "esperando_pagador"
    reply_button_data = member_select_message(number, options, body, footer, "sed1")
    user_responses.append(reply_button_data)

    return user_responses, estado_actual_usuario


def handle_waiting_for_payer(
    number: str, estado_actual_usuario: Dict[str, Any], message_id: str, text: str, member_service: MemberService
) -> Tuple[List[str], Dict[str, Any]]:
    """handle waiting for payer"""
    user_responses = []

    payer_id = member_service.get_member_id_by_name(text.lower())

    if payer_id is None:
        error_message = text_message(
            number, "❌ No se encontró a la persona seleccionada. Por favor, intenta de nuevo."
        )
        user_responses.append(error_message)
        return user_responses, estado_actual_usuario

    estado_actual_usuario["expense_data"]["payer_id"] = payer_id

    body = (
        "📅 ¿Cuándo se realizó el gasto?\n\n"
        "_o escribí la fecha:_\n"
        "_DD/MM/AAAA, DD-MM-AAAA, DD-MM o DD/MM (año actual)_"
    )
    footer = "⚙️ Admin Gastos Compartidos ⚙️"
    options = ["Hoy", "Ayer"]
    reply_button_data = button_reply_message(number, options, body, footer, "sed_fecha")
    user_responses.append(reply_button_data)

    estado_actual_usuario["estado"] = "esperando_fecha_pago"

    return user_responses, estado_actual_usuario


def handle_waiting_for_payment_date(  # pylint: disable=too-many-locals
    number: str, estado_actual_usuario: Dict[str, Any], text: str, member_service: MemberService, message_id: str
) -> Tuple[List[str], Dict[str, Any]]:
    """handle waiting for payment date"""
    user_responses = []
    try:
        estado_actual_usuario["expense_data"]["date"] = parse_user_date(text).isoformat()

        # SI ES UN PRESTAMO, LUEGO DE LA FECHA YA PODEMOS CARGARLO ##
        if estado_actual_usuario["expense_data"]["service"] == "prestar plata":
            print("cargando el prestamo...")
            payer_id = estado_actual_usuario["expense_data"]["payer_id"]
            all_members = member_service.list_members()
            non_payer_ids = [m.id for m in all_members if m.id != payer_id]

            if len(non_payer_ids) == 1:
                # 2-member fast-path: auto-assign the only non-payer as recipient
                id_of_not_payer = non_payer_ids[0]
                split_strategy_dict = {
                    "type": "percentage",
                    "percentages": {payer_id: 0, id_of_not_payer: 100},
                }
                estado_actual_usuario["expense_data"]["payment_type"] = "debito"
                estado_actual_usuario["expense_data"]["category"] = "prestamo"
                estado_actual_usuario["expense_data"]["split_strategy"] = split_strategy_dict

                conf_responses, estado_actual_usuario = _make_confirmation_response(
                    number, estado_actual_usuario, None, member_service
                )
                user_responses.extend(conf_responses)
            else:
                # N-member path: ask who receives the loan
                non_payer_names = [member_service.get_member_name_by_id(mid) for mid in non_payer_ids]
                body = "👤 ¿A quién le estás prestando el dinero?\n\nSelecciona el destinatario ⬇️"
                footer = "⚙️ Admin Gastos Compartidos ⚙️"
                reply_data = member_select_message(number, non_payer_names, body, footer, "sed1")
                user_responses.append(reply_data)
                estado_actual_usuario["estado"] = "esperando_destinatario_prestamo"

        else:
            user_responses.append(category_select_message(number))
            estado_actual_usuario["estado"] = "esperando_categoria"

    except ValueError:
        user_responses.append(
            text_message(
                number,
                "❌ No pude entender la fecha. Podés escribir _hoy_, _ayer_, "
                "o una fecha como _15/03/2025_, _15-03-2025_ o _15-03_.",
            )
        )
        return user_responses, estado_actual_usuario
    return user_responses, estado_actual_usuario


def handle_waiting_for_loan_recipient(
    number: str, estado_actual_usuario: Dict[str, Any], text: str, member_service: MemberService
) -> Tuple[List[str], Dict[str, Any]]:
    """handle N-member loan: resolve recipient by name and build the split strategy."""
    user_responses = []
    payer_id = estado_actual_usuario["expense_data"]["payer_id"]
    recipient_id = member_service.get_member_id_by_name(text.lower())

    if recipient_id is None or recipient_id == payer_id:
        error_message = text_message(number, "❌ No se encontró al destinatario. Por favor, intenta de nuevo.")
        user_responses.append(error_message)
        return user_responses, estado_actual_usuario

    split_strategy_dict = {
        "type": "percentage",
        "percentages": {payer_id: 0, recipient_id: 100},
    }
    estado_actual_usuario["expense_data"]["payment_type"] = "debito"
    estado_actual_usuario["expense_data"]["category"] = "prestamo"
    estado_actual_usuario["expense_data"]["split_strategy"] = split_strategy_dict

    conf_responses, estado_actual_usuario = _make_confirmation_response(
        number, estado_actual_usuario, None, member_service
    )
    user_responses.extend(conf_responses)

    return user_responses, estado_actual_usuario


def handle_waiting_for_category(
    number: str,
    estado_actual_usuario: Dict[str, Any],
    text: str,
    message_id: str,
    interactive_id: Optional[str] = None,
) -> Tuple[List[str], Dict[str, Any]]:
    """handle waiting for category"""
    user_responses = []
    print("esperando_categoria")

    resolved_category: Optional[str] = None

    # Only accept interactive list reply with cat_<name> ID — no typed number/name fallback
    if interactive_id and interactive_id.startswith("cat_"):
        cat_name = interactive_id[len("cat_") :]
        if Category.is_valid_category(cat_name) and not Category.is_internal_category(cat_name):
            resolved_category = cat_name

    if resolved_category is None:
        error_prefix = text_message(number, "❌ Por favor, seleccioná una categoría de la lista.")
        user_responses.append(error_prefix)
        user_responses.append(category_select_message(number))
        return user_responses, estado_actual_usuario

    estado_actual_usuario["expense_data"]["category"] = resolved_category

    body = "💳 ¿Qué método de pago se utilizó?\n\nSelecciona una opción ⬇️"
    footer = "⚙️ Admin Gastos Compartidos ⚙️"
    options = ["💰 Débito", "💳 Crédito 1 cuota", "💳 Crédito en cuotas"]

    reply_button_data = button_reply_message(number, options, body, footer, "sed1")
    user_responses.append(reply_button_data)

    estado_actual_usuario["estado"] = "esperando_tipo_pago"

    return user_responses, estado_actual_usuario


def handle_waiting_for_payment_type(
    number: str, estado_actual_usuario: Dict[str, Any], message_id: str, text: str
) -> Tuple[List[str], Dict[str, Any]]:
    """handle waiting for payment — 3 options: Débito / Crédito 1 cuota / Crédito en cuotas"""
    user_responses = []

    print("esperando_tipo_pago")

    text_lower = text.lower()
    if "1 cuota" in text_lower:
        # Crédito, single installment — skip cuotas question
        estado_actual_usuario["expense_data"]["payment_type"] = "credito"
        estado_actual_usuario["expense_data"]["installments"] = 1
        body = "📊 ¿Cómo deseas dividir el gasto?"
        footer = "⚙️ Admin Gastos Compartidos ⚙️"
        options = ["⚖️ Partes iguales", "📊 Por porcentajes", "💵 Montos exactos"]
        reply_button_data = button_reply_message(number, options, body, footer, "sed1")
        user_responses.append(reply_button_data)
        estado_actual_usuario["estado"] = "esperando_estrategia"
    elif "cuotas" in text_lower or "crédito" in text_lower or "credito" in text_lower:
        # Crédito en cuotas — ask how many
        estado_actual_usuario["expense_data"]["payment_type"] = "credito"
        body = "🔢 ¿En cuántas cuotas?"
        reply_text = reply_text_message(number, message_id, body)
        user_responses.append(reply_text)
        estado_actual_usuario["estado"] = "esperando_cuotas"
    else:
        # Débito (default)
        estado_actual_usuario["expense_data"]["payment_type"] = "debito"
        body = "📊 ¿Cómo deseas dividir el gasto?"
        footer = "⚙️ Admin Gastos Compartidos ⚙️"
        options = ["⚖️ Partes iguales", "📊 Por porcentajes", "💵 Montos exactos"]
        reply_button_data = button_reply_message(number, options, body, footer, "sed1")
        user_responses.append(reply_button_data)
        estado_actual_usuario["estado"] = "esperando_estrategia"

    return user_responses, estado_actual_usuario


def handle_waiting_for_installments(
    number: str, estado_actual_usuario: Dict[str, Any], text: str
) -> Tuple[List[str], Dict[str, Any]]:
    """handle waiting for installments"""
    user_responses = []
    print("esperando_cuotas")
    try:
        cuotas = int(text)
        if cuotas < 2:
            raise ValueError("Número de cuotas inválido")
        estado_actual_usuario["expense_data"]["installments"] = cuotas

        body = "📊 ¿Cómo deseas dividir el gasto?"
        footer = "⚙️ Admin Gastos Compartidos ⚙️"
        options = ["⚖️ Partes iguales", "📊 Por porcentajes", "💵 Montos exactos"]

        reply_button_data = button_reply_message(number, options, body, footer, "sed1")
        user_responses.append(reply_button_data)

        estado_actual_usuario["estado"] = "esperando_estrategia"

    except ValueError:
        error_message = text_message(number, "Ingresá un número entero de cuotas (2 o más).")
        user_responses.append(error_message)

    return user_responses, estado_actual_usuario


def parse_user_date(text: str) -> date:
    """Parse flexible date input: 'hoy', 'ayer', DD-MM, DD/MM, DD-MM-YYYY, DD/MM/YYYY.

    Raises ValueError if none of the patterns match.
    """
    normalized = text.strip().lower()
    today = datetime.now().date()
    if normalized == "hoy":
        return today
    if normalized == "ayer":
        from datetime import timedelta  # pylint: disable=C0415

        return today - timedelta(days=1)
    patterns = ["%d-%m-%Y", "%d/%m/%Y", "%d-%m", "%d/%m"]
    for fmt in patterns:
        try:
            parsed = datetime.strptime(normalized, fmt)
            if fmt in ("%d-%m", "%d/%m"):
                return parsed.replace(year=today.year).date()
            return parsed.date()
        except ValueError:
            continue
    raise ValueError(f"No se pudo interpretar la fecha: {text!r}")


def get_expense_summary(  # pylint: disable=too-many-locals
    expense_data: Dict[str, Any], member_service: MemberService
) -> str:
    """Generate a summary of the expense for confirmation."""
    is_loan = expense_data.get("service") == "prestar plata"
    header = "📝 *Resumen del préstamo:*" if is_loan else "📝 *Resumen del gasto:*"

    installments = expense_data.get("installments", 1) or 1
    payment_type_raw = expense_data.get("payment_type", "")
    payer_id = expense_data.get("payer_id")
    category_name = expense_data.get("category", "")

    summary = [
        header,
        f"💬 Descripción: {expense_data.get('description', '')}",
        f"💰 Monto: ${format_amount_es(expense_data.get('amount', 0))}",
        f"📅 Fecha: {format_date_es(expense_data.get('date', ''))}",
        f"📂 Categoría: {format_category_es(category_name)}",
        f"👤 Pagador: {format_member_name_es(payer_id, member_service)}",
        f"💳 Método de pago: {format_payment_type_es(payment_type_raw, installments)}",
    ]

    split_strategy = expense_data.get("split_strategy", {})
    if split_strategy:
        strategy_type = split_strategy.get("type", "")
        if strategy_type == "equal" and split_strategy.get("participant_ids"):
            names = [format_member_name_es(int(mid), member_service) for mid in split_strategy["participant_ids"]]
            summary.append("💡 División: Partes iguales entre " + ", ".join(names))
        elif strategy_type == "equal":
            summary.append("💡 División: Partes iguales")
        elif strategy_type == "percentage":
            percentages = split_strategy.get("percentages", {})
            summary.append("\n💹 *Porcentajes de división:*")
            for member_id, percentage in percentages.items():
                name = format_member_name_es(int(member_id), member_service)
                summary.append(f"- {name}: {percentage}%")
        elif strategy_type == "exact":
            amounts = split_strategy.get("amounts", {})
            summary.append("\n💵 *Montos asignados:*")
            for member_id, amount_val in amounts.items():
                name = format_member_name_es(int(member_id), member_service)
                summary.append(f"- {name}: ${format_amount_es(amount_val)}")

    return "\n".join(summary)


def handle_waiting_for_split_strategy(  # pylint: disable=too-many-locals,too-many-branches
    number: str,
    estado_actual_usuario: Dict[str, Any],
    message_id: str,
    text: str,
    member_service: MemberService,
    interactive_id: Optional[str] = None,
    service: Optional[ExpenseService] = None,
) -> Tuple[List[str], Dict[str, Any]]:
    """handle waiting for split — 3 options: Partes iguales / Porcentajes / Montos exactos"""
    user_responses = []

    print("esperando_estrategia")

    text_lower = text.lower()
    is_percentage = interactive_id == "sed_split_btn_2" or "porcentaje" in text_lower
    is_exact = (
        interactive_id == "sed_split_btn_3"
        or "exacto" in text_lower
        or ("monto" in text_lower and "porcentaje" not in text_lower)
    )

    if is_percentage:
        payer_id = estado_actual_usuario["expense_data"]["payer_id"]
        all_members = member_service.list_members()
        non_payer_ids = [m.id for m in all_members if m.id != payer_id]

        if len(non_payer_ids) == 1:
            body = (
                "📊 ¿Qué porcentaje corresponde al pagador?\n\n"
                "Por favor, ingresa solo el número sin símbolos\n\n"
                "✨ Ejemplo: 65.4"
            )
            reply_text = reply_text_message(number, message_id, body)
            user_responses.append(reply_text)
            estado_actual_usuario["estado"] = "esperando_porcentaje"
        else:
            estado_actual_usuario["expense_data"]["remaining_member_ids"] = non_payer_ids
            estado_actual_usuario["expense_data"]["pending_percentages"] = {}
            first_name = member_service.get_member_name_by_id(non_payer_ids[0])
            body = (
                f"📊 ¿Qué porcentaje le corresponde a {first_name}?\n\n"
                "Por favor, ingresa solo el número sin símbolos\n\n"
                "✨ Ejemplo: 35.0"
            )
            reply_text = reply_text_message(number, message_id, body)
            user_responses.append(reply_text)
            estado_actual_usuario["estado"] = "esperando_porcentaje_para_miembro"

    elif is_exact:
        payer_id = estado_actual_usuario["expense_data"]["payer_id"]
        all_members = member_service.list_members()
        non_payer_ids = [m.id for m in all_members if m.id != payer_id]
        total = estado_actual_usuario["expense_data"]["amount"]

        estado_actual_usuario["expense_data"]["remaining_member_ids"] = non_payer_ids
        estado_actual_usuario["expense_data"]["pending_amounts"] = {}
        first_name = member_service.get_member_name_by_id(non_payer_ids[0])
        body = (
            f"💵 ¿Cuánto le corresponde a {first_name}?\n\n"
            f"Total del gasto: ${format_amount_es(total)}\n"
            f"Asignado hasta ahora: $0,00\n"
            f"Restante por asignar: ${format_amount_es(total)}\n\n"
            "_Podés escribir el monto con punto o coma (ej: 250 o 250,50)._"
        )
        user_responses.append(reply_text_message(number, message_id, body))
        estado_actual_usuario["estado"] = "esperando_monto_para_miembro"

    else:
        # Partes iguales
        all_members = member_service.list_members()
        if len(all_members) >= 3:
            body = "👥 ¿Quiénes participan en este gasto?"
            footer = "⚙️ Admin Gastos Compartidos ⚙️"
            options = ["👥 Todos participan", "✂️ Excluir a alguien"]
            reply_button_data = button_reply_message(number, options, body, footer, "sed_part")
            user_responses.append(reply_button_data)
            estado_actual_usuario["estado"] = "esperando_definicion_participantes"
        else:
            strategy_dict: Dict[str, Any] = {"type": "equal"}
            estado_actual_usuario["expense_data"]["split_strategy"] = strategy_dict
            conf_responses, estado_actual_usuario = _make_confirmation_response(
                number, estado_actual_usuario, service, member_service
            )
            user_responses.extend(conf_responses)

    return user_responses, estado_actual_usuario


def handle_waiting_for_participants_definition(
    number: str,
    estado_actual_usuario: Dict[str, Any],
    text: str,
    member_service: MemberService,
    interactive_id: Optional[str] = None,
    service: Optional[ExpenseService] = None,
) -> Tuple[List[str], Dict[str, Any]]:
    """Two-button branch: 'Todos participan' vs 'Excluir a alguien'."""
    user_responses = []

    text_lower = text.lower()
    wants_exclude = interactive_id == "sed_part_btn_2" or "excluir" in text_lower or "alguien" in text_lower

    if wants_exclude:
        all_members = member_service.list_members()
        estado_actual_usuario["expense_data"]["excluded_member_ids"] = []
        estado_actual_usuario["expense_data"]["all_member_ids"] = [m.id for m in all_members]
        user_responses.append(_exclusion_list_message(number, all_members, []))
        estado_actual_usuario["estado"] = "esperando_excluidos"
    else:
        # Todos participan
        estado_actual_usuario["expense_data"]["split_strategy"] = {"type": "equal"}
        conf_responses, estado_actual_usuario = _make_confirmation_response(
            number, estado_actual_usuario, service, member_service
        )
        user_responses.extend(conf_responses)

    return user_responses, estado_actual_usuario


def _exclusion_list_message(number: str, all_members: list, excluded_ids: List[int]) -> str:
    """Build a list_reply showing remaining members to exclude plus a 'Listo' sentinel."""
    rows = []
    for m in all_members:
        if m.id not in excluded_ids:
            rows.append({"id": f"exc_{m.id}", "title": m.name, "description": ""})
    rows.append({"id": "exc_done", "title": "✅ Listo", "description": "Terminar selección"})

    excluded_names = [m.name for m in all_members if m.id in excluded_ids]
    excluded_str = ", ".join(excluded_names) if excluded_names else "nadie aún"
    body = f"✂️ Tocá los miembros que NO participan.\nExcluidos: {excluded_str}"

    return json.dumps(
        {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": number,
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {"text": body},
                "footer": {"text": "⚙️ Admin Gastos Compartidos ⚙️"},
                "action": {
                    "button": "Ver Miembros",
                    "sections": [{"title": "Miembros", "rows": rows}],
                },
            },
        }
    )


def handle_waiting_for_excluded_members(  # pylint: disable=too-many-locals
    number: str,
    estado_actual_usuario: Dict[str, Any],
    member_service: MemberService,
    interactive_id: Optional[str] = None,
    service: Optional[ExpenseService] = None,
) -> Tuple[List[str], Dict[str, Any]]:
    """Toggle-list: accumulate excluded members, finalise on 'Listo'."""
    user_responses = []
    all_members = member_service.list_members()
    excluded_ids: List[int] = estado_actual_usuario["expense_data"].get("excluded_member_ids", [])
    all_ids = [m.id for m in all_members]

    if interactive_id == "exc_done" or not interactive_id:
        # Finalise
        if not excluded_ids:
            participant_ids = None  # all members
        else:
            participant_ids = [mid for mid in all_ids if mid not in excluded_ids]
            if not participant_ids:
                # Everyone excluded — re-prompt
                user_responses.append(
                    _exclusion_list_message(
                        number,
                        all_members,
                        excluded_ids,
                    )
                )
                error = json.dumps(
                    {
                        "messaging_product": "whatsapp",
                        "recipient_type": "individual",
                        "to": number,
                        "type": "text",
                        "text": {"body": "❌ Debe participar al menos una persona. Seleccioná quién excluir."},
                    }
                )
                user_responses.insert(0, error)
                return user_responses, estado_actual_usuario

        strategy_dict: Dict[str, Any] = {"type": "equal"}
        if participant_ids is not None:
            strategy_dict["participant_ids"] = participant_ids

        estado_actual_usuario["expense_data"]["split_strategy"] = strategy_dict
        estado_actual_usuario["expense_data"].pop("excluded_member_ids", None)
        estado_actual_usuario["expense_data"].pop("all_member_ids", None)

        conf_responses, estado_actual_usuario = _make_confirmation_response(
            number, estado_actual_usuario, service, member_service
        )
        user_responses.extend(conf_responses)

    elif interactive_id.startswith("exc_"):
        member_id = int(interactive_id[len("exc_") :])
        if member_id not in excluded_ids:
            excluded_ids.append(member_id)
        estado_actual_usuario["expense_data"]["excluded_member_ids"] = excluded_ids
        user_responses.append(_exclusion_list_message(number, all_members, excluded_ids))

    else:
        user_responses.append(_exclusion_list_message(number, all_members, excluded_ids))

    return user_responses, estado_actual_usuario


def handle_waiting_for_amount_for_member(  # pylint: disable=too-many-locals
    number: str,
    estado_actual_usuario: Dict[str, Any],
    text: str,
    message_id: str,
    member_service: MemberService,
    service: Optional[ExpenseService] = None,
) -> Tuple[List[str], Dict[str, Any]]:
    """Queue-based exact amounts: collect one dollar amount per non-payer, then finalise."""
    user_responses = []
    total: float = estado_actual_usuario["expense_data"]["amount"]

    try:
        value = float(text.strip().replace(",", "."))
        if value < 0:
            raise ValueError("El monto no puede ser negativo")

        remaining: List[int] = estado_actual_usuario["expense_data"]["remaining_member_ids"]
        pending: Dict[int, float] = estado_actual_usuario["expense_data"]["pending_amounts"]
        current_id = remaining[0]

        assigned_so_far = sum(pending.values())
        if assigned_so_far + value > total + 0.01:
            raise ValueError(
                f"El total asignado (${format_amount_es(assigned_so_far + value)}) supera el gasto "
                f"(${format_amount_es(total)}). Te quedan ${format_amount_es(total - assigned_so_far)}."
            )

        pending[current_id] = value
        remaining = remaining[1:]
        assigned_so_far = sum(pending.values())

        estado_actual_usuario["expense_data"]["remaining_member_ids"] = remaining
        estado_actual_usuario["expense_data"]["pending_amounts"] = pending

        if remaining:
            next_name = member_service.get_member_name_by_id(remaining[0])
            remaining_amt = round(total - assigned_so_far, 2)
            body = (
                f"💵 ¿Cuánto le corresponde a {next_name}?\n\n"
                f"Total del gasto: ${format_amount_es(total)}\n"
                f"Asignado hasta ahora: ${format_amount_es(assigned_so_far)}\n"
                f"Restante por asignar: ${format_amount_es(remaining_amt)}\n\n"
                "_Podés escribir el monto con punto o coma (ej: 250 o 250,50)._"
            )
            user_responses.append(reply_text_message(number, message_id, body))
        else:
            payer_id = estado_actual_usuario["expense_data"]["payer_id"]
            payer_share = round(total - assigned_so_far, 2)
            if payer_share < -0.01:
                raise ValueError(f"Los montos asignados superan el total del gasto (${format_amount_es(total)})")
            payer_share = max(payer_share, 0.0)

            amounts: Dict[int, float] = {payer_id: payer_share}
            amounts.update({int(mid): amt for mid, amt in pending.items()})

            estado_actual_usuario["expense_data"]["split_strategy"] = {
                "type": "exact",
                "amounts": amounts,
            }
            del estado_actual_usuario["expense_data"]["remaining_member_ids"]
            del estado_actual_usuario["expense_data"]["pending_amounts"]

            conf_responses, estado_actual_usuario = _make_confirmation_response(
                number, estado_actual_usuario, service, member_service
            )
            user_responses.extend(conf_responses)

    except ValueError as e:
        error_message = text_message(number, f"❌ {str(e)}")
        user_responses.append(error_message)

    return user_responses, estado_actual_usuario


def handle_waiting_for_percentage(
    number: str,
    estado_actual_usuario: Dict[str, Any],
    text: str,
    member_service: MemberService,
    service: Optional[ExpenseService] = None,
) -> Tuple[List[str], Dict[str, Any]]:
    """handle waiting for percentage"""
    user_responses = []
    print("esperando_porcentaje")
    try:
        payer_percentage = float(text.strip().replace(",", "."))
        payer_id = estado_actual_usuario["expense_data"]["payer_id"]
        all_members = member_service.list_members()
        id_of_not_payer = next(m.id for m in all_members if m.id != payer_id)

        if not 0 <= payer_percentage <= 100:
            raise ValueError("El porcentaje debe estar entre 0 y 100")
        strategy_dict = {
            "type": "percentage",
            "percentages": {
                payer_id: payer_percentage,
                id_of_not_payer: round(100 - payer_percentage, 2),
            },
        }
        estado_actual_usuario["expense_data"]["split_strategy"] = strategy_dict

        conf_responses, estado_actual_usuario = _make_confirmation_response(
            number, estado_actual_usuario, service, member_service
        )
        user_responses.extend(conf_responses)

    except ValueError as e:
        error_message = text_message(number, f"Error: {str(e)}. Por favor, ingresa un número entre 0 y 100.")
        user_responses.append(error_message)

    return user_responses, estado_actual_usuario


def handle_waiting_for_percentage_for_member(  # pylint: disable=too-many-locals
    number: str,
    estado_actual_usuario: Dict[str, Any],
    text: str,
    message_id: str,
    member_service: MemberService,
    service: Optional[ExpenseService] = None,
) -> Tuple[List[str], Dict[str, Any]]:
    """N-member percentage: collect one non-payer percentage per turn, then finalise."""
    user_responses = []
    try:
        percentage = float(text.strip().replace(",", "."))
        if not 0 <= percentage <= 100:
            raise ValueError("El porcentaje debe estar entre 0 y 100")

        remaining: List[int] = estado_actual_usuario["expense_data"]["remaining_member_ids"]
        pending: Dict[int, float] = estado_actual_usuario["expense_data"]["pending_percentages"]

        current_id = remaining[0]
        pending[current_id] = percentage
        remaining = remaining[1:]
        total_assigned = sum(pending.values())

        estado_actual_usuario["expense_data"]["remaining_member_ids"] = remaining
        estado_actual_usuario["expense_data"]["pending_percentages"] = pending

        if remaining:
            next_name = member_service.get_member_name_by_id(remaining[0])
            remaining_pct = round(100 - total_assigned, 2)
            body = (
                f"📊 ¿Qué porcentaje le corresponde a {next_name}?\n\n"
                f"Porcentaje restante disponible: {remaining_pct}%\n\n"
                "Por favor, ingresa solo el número sin símbolos\n\n"
                "✨ Ejemplo: 35.0"
            )
            user_responses.append(reply_text_message(number, message_id, body))
        else:
            payer_id = estado_actual_usuario["expense_data"]["payer_id"]
            payer_pct = round(100 - total_assigned, 2)
            if payer_pct < -0.01:
                raise ValueError("Los porcentajes suman más del 100%")
            payer_pct = max(payer_pct, 0.0)

            percentages: Dict[int, float] = {payer_id: payer_pct}
            percentages.update({int(mid): pct for mid, pct in pending.items()})

            estado_actual_usuario["expense_data"]["split_strategy"] = {
                "type": "percentage",
                "percentages": percentages,
            }
            del estado_actual_usuario["expense_data"]["remaining_member_ids"]
            del estado_actual_usuario["expense_data"]["pending_percentages"]

            conf_responses, estado_actual_usuario = _make_confirmation_response(
                number, estado_actual_usuario, service, member_service
            )
            user_responses.extend(conf_responses)

    except ValueError as e:
        error_message = text_message(number, f"Error: {str(e)}. Por favor, ingresa un número entre 0 y 100.")
        user_responses.append(error_message)

    return user_responses, estado_actual_usuario


def handle_quick_expense(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    number: str,
    estado_actual_usuario: Dict[str, Any],
    text: str,
    service: Optional[ExpenseService],
    member_service: MemberService,
) -> Tuple[List[str], Dict[str, Any]]:
    """Attempt to parse a free-form expense or loan message via LLM and enter the confirmation flow."""
    current_member = member_service.get_member_by_phone(number)
    if current_member is None:
        msg = text_message(number, "Lo siento, no entendí lo que dijiste. 🤔\n\n¿En qué puedo ayudarte?")
        return [msg], estado_actual_usuario

    members = member_service.list_members()
    member_dicts = [{"id": m.id, "name": m.name} for m in members]
    categories = Category.get_user_categories()

    parsed = parse_quick_expense(
        text=text,
        members=member_dicts,
        categories=categories,
        current_member_id=current_member.id,
    )

    if parsed is None:
        msg = text_message(number, "Lo siento, no entendí lo que dijiste. 🤔\n\n¿En qué puedo ayudarte?")
        return [msg], estado_actual_usuario

    if parsed.is_loan:
        if parsed.recipient_id is None:
            msg = text_message(
                number,
                "Lo siento, no pude identificar a quién le prestaste el dinero. 🤔\n\n¿En qué puedo ayudarte?",
            )
            return [msg], estado_actual_usuario

        estado_actual_usuario["expense_data"]["service"] = "prestar plata"
        estado_actual_usuario["expense_data"]["amount"] = parsed.amount
        estado_actual_usuario["expense_data"]["description"] = parsed.description
        estado_actual_usuario["expense_data"]["category"] = "prestamo"
        estado_actual_usuario["expense_data"]["payer_id"] = parsed.payer_id
        estado_actual_usuario["expense_data"]["date"] = parsed.expense_date.isoformat()
        estado_actual_usuario["expense_data"]["payment_type"] = "debito"
        estado_actual_usuario["expense_data"]["installments"] = 1
        estado_actual_usuario["expense_data"]["split_strategy"] = {
            "type": "percentage",
            "percentages": {parsed.payer_id: 0, parsed.recipient_id: 100},
        }
        return _make_confirmation_response(number, estado_actual_usuario, None, member_service)

    if service is None:
        msg = text_message(number, "Lo siento, no entendí lo que dijiste. 🤔\n\n¿En qué puedo ayudarte?")
        return [msg], estado_actual_usuario

    estado_actual_usuario["expense_data"]["service"] = "cargar gasto"
    estado_actual_usuario["expense_data"]["amount"] = parsed.amount
    estado_actual_usuario["expense_data"]["description"] = parsed.description
    estado_actual_usuario["expense_data"]["category"] = parsed.category
    estado_actual_usuario["expense_data"]["payer_id"] = parsed.payer_id
    estado_actual_usuario["expense_data"]["date"] = parsed.expense_date.isoformat()
    estado_actual_usuario["expense_data"]["payment_type"] = parsed.payment_type
    estado_actual_usuario["expense_data"]["installments"] = parsed.installments
    estado_actual_usuario["expense_data"]["split_strategy"] = parsed.split_strategy or {"type": "equal"}

    return _make_confirmation_response(number, estado_actual_usuario, service, member_service)


def _make_confirmation_response(  # pylint: disable=too-many-locals
    number: str,
    estado_actual_usuario: Dict[str, Any],
    service: Optional[ExpenseService],
    member_service: MemberService,
) -> Tuple[List[str], Dict[str, Any]]:
    """Check for duplicates then build either a duplicate warning or the normal confirmation message.

    Sets estado to 'esperando_confirmacion_duplicado' or 'esperando_confirmacion'.
    """
    expense_data = estado_actual_usuario["expense_data"]
    is_loan = expense_data.get("service") == "prestar plata"

    if not is_loan and service is not None:
        try:
            expense_date = date.fromisoformat(expense_data["date"])
            similar = service.find_similar_expenses(
                year=expense_date.year,
                month=expense_date.month,
                amount=expense_data["amount"],
                description=expense_data["description"],
                expense_date=expense_date,
            )
        except (ValueError, KeyError, TypeError):
            similar = []

        if similar:
            dup = similar[0]
            dup_date_str = dup.date.isoformat() if hasattr(dup.date, "isoformat") else str(dup.date)
            payer_name = member_service.get_member_name_by_id(dup.payer_id)
            warning = (
                "⚠️ *Encontré un gasto similar cargado previamente:*\n\n"
                f"💬 {dup.description.capitalize()}\n"
                f"💰 ${format_amount_es(dup.amount)}\n"
                f"📅 {format_date_es(dup_date_str)}\n"
                f"🏷️ {format_category_es(dup.category)}\n"
                f"💳 {format_payment_type_es(dup.payment_type, dup.installments)}\n"
                f"👤 {payer_name}\n\n"
                "¿Querés cargar el gasto de todos modos?"
            )
            dup_msg = button_reply_message(
                number,
                ["✅ Sí, agregar igual", "❌ No, cancelar"],
                warning,
                "⚙️ Admin Gastos Compartidos ⚙️",
                "sed_dup",
            )
            estado_actual_usuario["estado"] = "esperando_confirmacion_duplicado"
            return [dup_msg], estado_actual_usuario

    summary = get_expense_summary(expense_data, member_service)
    if is_loan:
        body = f"{summary}\n¿Confirmas que los datos son correctos?"
        options = ["✅ Sí, crear préstamo", "❌ No, cancelar"]
    else:
        body = f"{summary}\n\n¿Confirmas que los datos son correctos?"
        options = ["✅ Sí, crear gasto", "❌ No, cancelar"]

    msg = button_reply_message(number, options, body, "⚙️ Admin Gastos Compartidos ⚙️", "sed1")
    estado_actual_usuario["estado"] = "esperando_confirmacion"
    return [msg], estado_actual_usuario


def handle_waiting_for_duplicate_confirmation(
    number: str,
    estado_actual_usuario: Dict[str, Any],
    text: str,
    service: Optional[ExpenseService],
    member_service: MemberService,
    interactive_id: Optional[str] = None,
) -> Tuple[List[str], Dict[str, Any]]:
    """User responded to the duplicate-expense warning — proceed or cancel."""
    user_responses = []

    # Button ID "sed_dup_btn_1" = "Sí, agregar igual"
    confirmed = interactive_id == "sed_dup_btn_1" or "agregar igual" in text.lower()

    if confirmed:
        conf_responses, estado_actual_usuario = _make_confirmation_response(
            number, estado_actual_usuario, None, member_service
        )
        user_responses.extend(conf_responses)
    else:
        body = "Gasto cancelado. ¿Deseas realizar otra operación?"
        options = ["🏠 Ir al Inicio", "👋 No gracias"]
        reply_button_data = button_reply_message(number, options, body, "⚙️ Admin Gastos Compartidos ⚙️", "sed1")
        user_responses.append(reply_button_data)
        clean_estado_usuario(estado_actual_usuario)

    return user_responses, estado_actual_usuario


def handle_waiting_for_confirmation(
    number: str,
    estado_actual_usuario: Dict[str, Any],
    text: str,
    service: ExpenseService,
    member_service: MemberService,
) -> Tuple[List[str], Dict[str, Any]]:
    """handle waiting for confirmation"""
    user_responses = []

    if "crear" in text.lower():  # Confirmed
        split_strategy = estado_actual_usuario["expense_data"]["split_strategy"]
        try:
            create_expense(
                number,
                estado_actual_usuario,
                service,
                split_strategy_dict=split_strategy,
                member_service=member_service,
            )
            clean_estado_usuario(estado_actual_usuario)
            body = "✨ ¡Genial! El gasto ha sido registrado exitosamente.\n\n¿Deseas realizar otra operación?"
            options = ["🏠 Ir al Inicio", "👋 No gracias"]
            footer = "⚙️ Admin Gastos Compartidos ⚙️"
            reply_button_data = button_reply_message(number, options, body, footer, "sed1")
            user_responses.append(reply_button_data)
        except ValueError as exc:
            if "está saldado" in str(exc):
                expense_date = date.fromisoformat(estado_actual_usuario["expense_data"]["date"])
                month_str = month_name_es(expense_date.month)
                estado_actual_usuario["estado"] = "esperando_respuesta_mes_saldado"
                body = f"⚠️ El balance de *{month_str} {expense_date.year}* está saldado.\n\n" "¿Qué querés hacer?"
                reply_button_data = button_reply_message(
                    number,
                    ["🔓 Reabrir el mes", "📅 Cambiar la fecha"],
                    body,
                    "⚙️ Admin Gastos Compartidos ⚙️",
                    "sed_settled",
                )
                user_responses.append(reply_button_data)
            else:
                raise

    else:  # Cancelled
        body = "Gasto cancelado. ¿Deseas realizar otra operación?"
        options = ["🏠 Ir al Inicio", "👋 No gracias"]
        footer = "⚙️ Admin Gastos Compartidos ⚙️"

        reply_button_data = button_reply_message(number, options, body, footer, "sed1")
        user_responses.append(reply_button_data)

        clean_estado_usuario(estado_actual_usuario)

    return user_responses, estado_actual_usuario


def handle_waiting_for_settled_response(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    number: str,
    estado_actual_usuario: Dict[str, Any],
    text: str,
    service: ExpenseService,
    member_service: MemberService,
    interactive_id: Optional[str] = None,
) -> Tuple[List[str], Dict[str, Any]]:
    """User chose to reopen the month or change the date after a settled-month error."""
    user_responses = []
    reopening = interactive_id == "sed_settled_btn_1" or "reabrir" in text.lower()
    change_date = interactive_id == "sed_settled_btn_2" or "cambiar" in text.lower()

    if reopening:
        expense_date = date.fromisoformat(estado_actual_usuario["expense_data"]["date"])
        try:
            service.unsettle_monthly_share(expense_date.year, expense_date.month)
        except Exception:  # pylint: disable=broad-except
            pass
        split_strategy = estado_actual_usuario["expense_data"]["split_strategy"]
        try:
            create_expense(
                number,
                estado_actual_usuario,
                service,
                split_strategy_dict=split_strategy,
                member_service=member_service,
            )
            clean_estado_usuario(estado_actual_usuario)
            body = "✨ ¡El mes fue reabierto y el gasto registrado exitosamente!\n\n¿Deseas realizar otra operación?"
        except Exception:  # pylint: disable=broad-except
            clean_estado_usuario(estado_actual_usuario)
            body = "❌ No se pudo registrar el gasto. Intentalo de nuevo."
        options = ["🏠 Ir al Inicio", "👋 No gracias"]
        user_responses.append(button_reply_message(number, options, body, "⚙️ Admin Gastos Compartidos ⚙️", "sed1"))

    elif change_date:
        estado_actual_usuario["estado"] = "esperando_fecha_gasto_saldado"
        body = (
            "📅 ¿Cuál es la nueva fecha del gasto?\n\n"
            "_o escribí la fecha:_\n"
            "_DD/MM/AAAA, DD-MM-AAAA, DD-MM o DD/MM (año actual)_"
        )
        user_responses.append(
            button_reply_message(number, ["Hoy", "Ayer"], body, "⚙️ Admin Gastos Compartidos ⚙️", "sed_fecha_s")
        )

    else:
        expense_date = date.fromisoformat(estado_actual_usuario["expense_data"]["date"])
        month_str = month_name_es(expense_date.month)
        body = f"⚠️ El balance de *{month_str} {expense_date.year}* está saldado.\n\n" "¿Qué querés hacer?"
        user_responses.append(
            button_reply_message(
                number,
                ["🔓 Reabrir el mes", "📅 Cambiar la fecha"],
                body,
                "⚙️ Admin Gastos Compartidos ⚙️",
                "sed_settled",
            )
        )

    return user_responses, estado_actual_usuario


def handle_waiting_for_settled_date(
    number: str,
    estado_actual_usuario: Dict[str, Any],
    text: str,
    service: ExpenseService,
    member_service: MemberService,
) -> Tuple[List[str], Dict[str, Any]]:
    """User entered a new date after choosing to change it on a settled month."""
    user_responses = []
    try:
        new_date = parse_user_date(text)
        estado_actual_usuario["expense_data"]["date"] = new_date.isoformat()
        conf_responses, estado_actual_usuario = _make_confirmation_response(
            number, estado_actual_usuario, service, member_service
        )
        user_responses.extend(conf_responses)
    except ValueError:
        user_responses.append(
            text_message(
                number,
                "❌ No pude entender la fecha. Podés escribir _hoy_, _ayer_, "
                "o una fecha como _15/03/2025_, _15-03-2025_ o _15-03_.",
            )
        )
    return user_responses, estado_actual_usuario


def handle_no_thanks(
    number: str, estado_actual_usuario: Dict[str, Any], message_id: str
) -> Tuple[List[str], Dict[str, Any]]:
    """handle goodbye"""
    user_responses = []

    body = "👋 ¡Gracias por usar Jirens Shared Expenses! ¡Hasta pronto! ✨"
    reply_text = reply_text_message(number, message_id, body)
    user_responses.append(reply_text)

    estado_actual_usuario = clean_estado_usuario(estado_actual_usuario)

    return user_responses, estado_actual_usuario
