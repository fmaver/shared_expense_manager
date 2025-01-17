"""wpp service"""
import json
import os
import re
import time
from datetime import date, datetime
from typing import Any, Collection, Dict, List, Optional, Tuple

import requests

from template.domain.models.category import Category
from template.domain.models.enums import PaymentType
from template.domain.models.models import MonthlyShare
from template.domain.models.pdf_builder import ExpensePDF
from template.domain.schemas.expense import (
    CategorySchema,
    ExpenseCreate,
    SplitStrategySchema,
)
from template.service_layer.expense_service import ExpenseService


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

        # Log the response
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


# pylint: disable=too-many-branches, too-many-statements
# flake8: noqa: C901
def administrar_chatbot(
    text: str, number: str, message_id: str, estado_actual_usuario: Dict[str, Any], service: ExpenseService
) -> Dict[str, Any]:  # noqa: C901
    """logica del bot"""
    user_responses = []
    print("mensaje del usuario: ", text)
    print("estado actual del usuario: ", estado_actual_usuario["estado"])

    mark_read = mark_read_message(message_id)
    user_responses.append(mark_read)
    time.sleep(2)

    if "hola" in text.lower() or "inicio" in text.lower():
        responses, estado_actual_usuario = handle_greetings(number, estado_actual_usuario)
        user_responses.extend(responses)

    elif "no gracias" in text.lower():
        responses, estado_actual_usuario = handle_no_thanks(number, estado_actual_usuario, message_id)
        user_responses.extend(responses)

    elif "obtener documento" in text.lower():
        responses, estado_actual_usuario = handle_document_request(number, estado_actual_usuario, service)
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
        responses, estado_actual_usuario = handle_waiting_for_description(number, estado_actual_usuario, text)
        user_responses.extend(responses)

    elif estado_actual_usuario["estado"] == "esperando_pagador" and ("fran" in text.lower() or "guadi" in text.lower()):
        responses, estado_actual_usuario = handle_waiting_for_payer(number, estado_actual_usuario, message_id, text)
        user_responses.extend(responses)

    elif estado_actual_usuario["estado"] == "esperando_fecha_pago" and re.match(r"^\d{2}-\d{2}-\d{4}$", text):
        responses, estado_actual_usuario = handle_waiting_for_payment_date(
            number, estado_actual_usuario, text, service, message_id
        )
        user_responses.extend(responses)

    elif estado_actual_usuario["estado"] == "esperando_categoria":
        responses, estado_actual_usuario = handle_waiting_for_category(number, estado_actual_usuario, text, message_id)
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
            number, estado_actual_usuario, message_id, text, service
        )
        user_responses.extend(responses)

    elif estado_actual_usuario["estado"] == "esperando_porcentaje" and text.replace(".", "", 1).isdigit():
        responses, estado_actual_usuario = handle_waiting_for_percentage(number, estado_actual_usuario, text, service)
        user_responses.extend(responses)

    elif estado_actual_usuario["estado"] == "esperando_confirmacion":
        responses, estado_actual_usuario = handle_waiting_for_confirmation(number, estado_actual_usuario, text, service)
        user_responses.extend(responses)

    else:
        data = text_message(number, "Lo siento, no entendí lo que dijiste.")
        user_responses.append(data)

    for item in user_responses:
        print("enviando...", item)
        enviar_mensaje_whatsapp(item)

    return estado_actual_usuario  # noqa: C901


def create_expense(estado_actual_usuario: Dict[str, Any], service: ExpenseService, split_strategy_dict: Dict[str, Any]):
    """create expense"""
    payment_type = (
        PaymentType.CREDIT if estado_actual_usuario["expense_data"]["payment_type"] == "crédito" else PaymentType.DEBIT
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

    service.create_expense(expense_data)


# al parecer para mexico, whatsapp agrega 521 como prefijo en lugar de 52,
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
    return estado_actual_usuario


def handle_greetings(number: str, estado_actual_usuario: Dict[str, Any]) -> Tuple[List[str], Dict[str, Any]]:
    """handle greetings"""
    user_responses = []

    body = "👋 ¡Hola! Bienvenido a Jirense Expenses ✨\n¿Cómo podemos ayudarte hoy?"
    footer = "Fran y Guadi 💫"
    options = ["💰 Cargar Gasto", "💸 Prestar Plata", "📊 Generar Balance"]

    reply_button_data = button_reply_message(number, options, body, footer, "sed1")

    user_responses.append(reply_button_data)

    # Siempre que volvemos al estado inicial, reseteamos el estado del usuario
    estado_actual_usuario = clean_estado_usuario(estado_actual_usuario)

    return user_responses, estado_actual_usuario


def handle_document_request(
    number: str, estado_actual_usuario: Dict[str, Any], service: ExpenseService
) -> Tuple[List[str], Dict[str, Any]]:
    """handle document"""
    user_responses = []

    fecha = estado_actual_usuario["expense_data"]["date"]
    month_year = datetime.strptime(fecha, "%m-%Y")
    print("calculando balance para el mes y año: ", month_year.month, month_year.year)

    monthly_balance_dict = service.get_monthly_balance(month_year.year, month_year.month).balances  # Dict[str, float]
    print("monthly_balance_dict: ", monthly_balance_dict)
    monthly_expenses_list = service.get_monthly_expenses(month_year.year, month_year.month)

    print("instanciando el generador de PDF...")
    filename = f"balance_{month_year.month}_{month_year.year}.pdf"

    # Generar el PDF, utilizando como ruta de almacenamiento la variable de entorno STORAGE_PATH
    pdf_generator = ExpensePDF(storage_path=os.getenv("STORAGE_PATH", "/tmp/storage"))

    member_names_dict = service.get_member_names()  # Obtener nombres de miembros
    file_path = pdf_generator.generate_expense_report(
        monthly_expenses_list, monthly_balance_dict, filename, member_names_dict
    )
    print(f"Archivo PDF generado en: {file_path}")

    media_id = obtener_media_id(file_path)[0]

    caption = f"📑 Balance de Fran Y Guadi para {month_year.month}/{month_year.year}"

    document_data = document_message(number, media_id, caption, filename)
    user_responses.append(document_data)
    print("enviando documento...")

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
        footer = "Fran y Guadi"

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
        footer = "Fran y Guadi 💫"

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
            reply_button_data = button_reply_message(number, options, body, "Fran y Guadi 💫", "sed1")
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
✨ Ejemplo: 1234.56"""
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
✨ Ejemplo: 1234.56"""
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
        amount = float(text)
        estado_actual_usuario["expense_data"]["amount"] = amount

        body = "🖊️ ¿Cuál es el motivo del gasto?\n\nPor favor, escribe una breve descripción 📝"
        reply_text = reply_text_message(number, message_id, body)
        user_responses.append(reply_text)

        estado_actual_usuario["estado"] = "esperando_descripcion"

    except ValueError:
        error_message = text_message(number, "❌ El monto ingresado no es válido. Por favor, intenta de nuevo.")
        user_responses.append(error_message)

    return user_responses, estado_actual_usuario


def handle_waiting_for_description(
    number: str, estado_actual_usuario: Dict[str, Any], text: str
) -> Tuple[List[str], Dict[str, Any]]:
    """handle wiaitng for desc"""
    user_responses = []
    if estado_actual_usuario["expense_data"]["service"] == "cargar gasto":
        estado_actual_usuario["expense_data"]["description"] = text.lower()
        body = "👤 ¿Quién realizó el gasto?\n\nSelecciona la persona que pagó ⬇️"
    else:
        estado_actual_usuario["expense_data"]["description"] = f"{text.lower()}"
        body = "👤 ¿Quién realizó el préstamo?\n\nSelecciona la persona que prestó el dinero ⬇️"

    footer = "Fran y Guadi 💫"
    options = ["👨🏽‍💻 Fran", "👷🏽‍♀️ Guadi"]

    estado_actual_usuario["estado"] = "esperando_pagador"
    reply_button_data = button_reply_message(number, options, body, footer, "sed1")
    user_responses.append(reply_button_data)

    return user_responses, estado_actual_usuario


def handle_waiting_for_payer(
    number: str, estado_actual_usuario: Dict[str, Any], message_id: str, text: str
) -> Tuple[List[str], Dict[str, Any]]:
    """handle waiting for payer"""
    user_responses = []
    estado_actual_usuario["expense_data"]["payer_id"] = (
        1 if "fran" in text.lower() else 2
    )  # revisar si es la mejor forma de hacerlo

    body = """📅 ¿Cuándo se realizó el gasto?\n
Por favor, ingresa la fecha en el formato: DD-MM-AAAA\n
✨ Ejemplo: 01-01-2025"""
    reply_text = reply_text_message(number, message_id, body)
    user_responses.append(reply_text)

    estado_actual_usuario["estado"] = "esperando_fecha_pago"

    return user_responses, estado_actual_usuario


def handle_waiting_for_payment_date(
    number: str, estado_actual_usuario: Dict[str, Any], text: str, service: ExpenseService, message_id: str
) -> Tuple[List[str], Dict[str, Any]]:
    """handle waiting for payment date"""
    user_responses = []
    try:
        estado_actual_usuario["expense_data"]["date"] = datetime.strptime(text, "%d-%m-%Y").date()

        # SI ES UN PRESTAMO, LUEGO DE LA FECHA YA PODEMOS CARGARLO ##
        if estado_actual_usuario["expense_data"]["service"] == "prestar plata":
            print("cargando el prestamo...")
            id_of_not_payer = 1 if estado_actual_usuario["expense_data"]["payer_id"] == 2 else 2

            split_strategy_dict = {
                "type": "percentage",
                "percentages": {estado_actual_usuario["expense_data"]["payer_id"]: 0, id_of_not_payer: 100},
            }
            estado_actual_usuario["expense_data"]["payment_type"] = "debito"
            estado_actual_usuario["expense_data"]["category"] = "prestamo"
            estado_actual_usuario["expense_data"]["split_strategy"] = split_strategy_dict

            # Instead of creating the expense immediately, show summary and ask for confirmation
            summary = get_expense_summary(estado_actual_usuario["expense_data"])
            payer_name = "Fran" if estado_actual_usuario["expense_data"]["payer_id"] == 1 else "Guadi"
            other_name = "Guadi" if payer_name == "Fran" else "Fran"
            summary += f"""\n\n💡 División: {other_name} pagará el 100% (préstamo)\n\n
¿Confirmas que los datos son correctos?
"""

            options = ["✅ Sí, crear préstamo", "❌ No, cancelar"]

            reply_button_data = button_reply_message(number, options, summary, "Fran y Guadi", "sed1")
            user_responses.append(reply_button_data)

            estado_actual_usuario["estado"] = "esperando_confirmacion"

        else:
            categories_text = "\n".join([f"{num}: {cat}" for num, cat in Category.get_numbered_categories()])

            body = f"🏷️ Por favor, selecciona la categoría del gasto\n{categories_text}\n"
            user_responses.append(reply_text_message(number, message_id, body))

            estado_actual_usuario["estado"] = "esperando_categoria"

    except ValueError:
        user_responses.append(
            text_message(number, "El formato ingresado no es válido. Por favor, intenta de nuevo con\nDD-MM-AAAA.")
        )
        return user_responses, estado_actual_usuario

    return user_responses, estado_actual_usuario


def handle_waiting_for_category(
    number: str, estado_actual_usuario: Dict[str, Any], text: str, message_id: str
) -> Tuple[List[str], Dict[str, Any]]:
    """handle waiting for category"""
    user_responses = []
    print("esperando_categoria")

    # Try to get category by number first
    try:
        category_number = int(text)
        category = Category.get_category_by_number(category_number)
        if category:
            estado_actual_usuario["expense_data"]["category"] = category
        else:
            raise ValueError
    except ValueError:
        # If not a number or invalid number, try as category name
        text = text.lower()
        if Category.is_valid_category(text):
            estado_actual_usuario["expense_data"]["category"] = text
        else:
            numbered_categories = Category.get_numbered_categories()
            categories_text = "\n".join([f"{num}: {cat}" for num, cat in numbered_categories])
            body = f"Categoría no válida. Por favor elige una de las siguientes:\n{categories_text}"
            reply_text = reply_text_message(number, message_id, body)
            user_responses.append(reply_text)
            return user_responses, estado_actual_usuario

    body = "💳 ¿Qué método de pago se utilizó?\n\nSelecciona una opción ⬇️"
    footer = "Fran y Guadi 💫"
    options = ["💳 Crédito", "💰 Débito"]

    reply_button_data = button_reply_message(number, options, body, footer, "sed1")
    user_responses.append(reply_button_data)

    estado_actual_usuario["estado"] = "esperando_tipo_pago"

    return user_responses, estado_actual_usuario


def handle_waiting_for_payment_type(
    number: str, estado_actual_usuario: Dict[str, Any], message_id: str, text: str
) -> Tuple[List[str], Dict[str, Any]]:
    """handle waiting for payment"""
    user_responses = []

    print("esperando_tipo_pago")
    estado_actual_usuario["expense_data"]["payment_type"] = text.lower()

    if "crédito" in text.lower():
        body = "📅 Por favor, indica el número de cuotas (1-12)"
        reply_text = reply_text_message(number, message_id, body)
        user_responses.append(reply_text)
        estado_actual_usuario["estado"] = "esperando_cuotas"
    else:
        body = "📊 ¿Cómo deseas dividir el gasto?"
        footer = "Fran y Guadi"
        options = ["🔄 Partes Iguales", "📊 Porcentajes"]

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
        estado_actual_usuario["expense_data"]["installments"] = int(text)

        body = "📊 ¿Cómo deseas dividir el gasto?"
        footer = "Fran y Guadi"
        options = ["🔄 Partes Iguales", "📊 Porcentajes"]

        reply_button_data = button_reply_message(number, options, body, footer, "sed1")
        user_responses.append(reply_button_data)

        estado_actual_usuario["estado"] = "esperando_estrategia"

    except ValueError:
        error_message = text_message(
            number, "La cantidad de cuotas ingresada no es válida. Por favor, intenta de nuevo."
        )
        user_responses.append(error_message)

    return user_responses, estado_actual_usuario


def get_expense_summary(expense_data: Dict[str, Any]) -> str:
    """Generate a summary of the expense for confirmation"""
    payer_id = expense_data.get("payer_id")
    payer_name = "Fran" if payer_id == 1 else "Guadi"
    expense_date: Optional[date] = expense_data.get("date")
    payment_type: Optional[str] = expense_data.get("payment_type")

    summary = f"""📝 *Resumen del gasto:*
💰 Monto: ${expense_data.get('amount')}
📝 Descripción: {expense_data.get('description')}
👤 Pagador: {payer_name}
📅 Fecha: {expense_date.strftime('%d-%m-%Y') if expense_date else 'No especificada'}
🏷️ Categoría: {expense_data.get('category')}
💳 Tipo de pago: {payment_type}"""

    if payment_type and payment_type.lower() == "crédito":
        summary += f"\n📅 Cuotas: {expense_data.get('installments')}"

    return summary


def handle_waiting_for_split_strategy(
    number: str, estado_actual_usuario: Dict[str, Any], message_id: str, text: str, service: ExpenseService
) -> Tuple[List[str], Dict[str, Any]]:
    """handle waiting for split"""
    user_responses = []

    print("esperando_estrategia")

    if "porcentaje" in text.lower():
        body = """📊 ¿Qué porcentaje corresponde al pagador?\n\nPor favor, ingresa solo el número sin símbolos\n
✨ Ejemplo: 65.4"""
        reply_text = reply_text_message(number, message_id, body)
        user_responses.append(reply_text)
        estado_actual_usuario["estado"] = "esperando_porcentaje"

    else:
        strategy_dict: Dict[str, Optional[Collection[Any]]] = {
            "type": "equal",
            "percentages": None,
        }
        estado_actual_usuario["expense_data"]["split_strategy"] = strategy_dict

        # Instead of creating the expense, show summary and ask for confirmation
        summary = get_expense_summary(estado_actual_usuario["expense_data"])
        summary += "\n\n💡 División: Equitativa"

        body = f"{summary}\n\n¿Confirmas que los datos son correctos?"
        options = ["✅ Sí, crear gasto", "❌ No, cancelar"]

        reply_button_data = button_reply_message(number, options, body, "Fran y Guadi", "sed1")
        user_responses.append(reply_button_data)

        estado_actual_usuario["estado"] = "esperando_confirmacion"

    return user_responses, estado_actual_usuario


def handle_waiting_for_percentage(
    number: str, estado_actual_usuario: Dict[str, Any], text: str, service: ExpenseService
) -> Tuple[List[str], Dict[str, Any]]:
    """handle waiting for percentage"""
    user_responses = []
    print("esperando_porcentaje")
    try:
        payer_percentage = float(text)
        id_of_not_payer = 1 if estado_actual_usuario["expense_data"]["payer_id"] == 2 else 2

        if not 0 <= payer_percentage <= 100:
            raise ValueError("El porcentaje debe estar entre 0 y 100")

        strategy_dict = {
            "type": "percentage",
            "percentages": {
                estado_actual_usuario["expense_data"]["payer_id"]: payer_percentage,
                id_of_not_payer: 100 - payer_percentage,
            },
        }
        estado_actual_usuario["expense_data"]["split_strategy"] = strategy_dict

        # Instead of creating the expense, show summary and ask for confirmation
        summary = get_expense_summary(estado_actual_usuario["expense_data"])
        payer_name = "Fran" if estado_actual_usuario["expense_data"]["payer_id"] == 1 else "Guadi"
        other_name = "Guadi" if payer_name == "Fran" else "Fran"
        summary += f"""\n\n💡 División: {payer_name}: {payer_percentage}%, {other_name}: {100 - payer_percentage}%
                        \n\n¿Confirmas que los datos son correctos?
                    """

        options = ["✅ Sí, crear gasto", "❌ No, cancelar"]

        reply_button_data = button_reply_message(number, options, summary, "Fran y Guadi", "sed1")
        user_responses.append(reply_button_data)

        estado_actual_usuario["estado"] = "esperando_confirmacion"

    except ValueError as e:
        error_message = text_message(number, f"Error: {str(e)}. Por favor, ingresa un número entre 0 y 100.")
        user_responses.append(error_message)

    return user_responses, estado_actual_usuario


def handle_waiting_for_confirmation(
    number: str, estado_actual_usuario: Dict[str, Any], text: str, service: ExpenseService
) -> Tuple[List[str], Dict[str, Any]]:
    """handle waiting for confirmation"""
    user_responses = []

    if "crear gasto" in text.lower():  # Confirmed
        split_strategy = estado_actual_usuario["expense_data"]["split_strategy"]
        create_expense(estado_actual_usuario, service, split_strategy_dict=split_strategy)

        body = "✨ ¡Genial! El gasto ha sido registrado exitosamente.\n\n¿Deseas realizar otra operación?"
        options = ["🏠 Ir al Inicio", "👋 No gracias"]
        footer = "Fran y Guadi"

        reply_button_data = button_reply_message(number, options, body, footer, "sed1")
        user_responses.append(reply_button_data)

    else:  # Cancelled
        body = "Gasto cancelado. ¿Deseas realizar otra operación?"
        options = ["🏠 Ir al Inicio", "👋 No gracias"]
        footer = "Fran y Guadi"

        reply_button_data = button_reply_message(number, options, body, footer, "sed1")
        user_responses.append(reply_button_data)

        clean_estado_usuario(estado_actual_usuario)

    return user_responses, estado_actual_usuario


def handle_no_thanks(
    number: str, estado_actual_usuario: Dict[str, Any], message_id: str
) -> Tuple[List[str], Dict[str, Any]]:
    """handle goodbye"""
    user_responses = []

    body = "👋 ¡Gracias por usar F&G Expenses! ¡Hasta pronto! ✨"
    reply_text = reply_text_message(number, message_id, body)
    user_responses.append(reply_text)

    estado_actual_usuario = clean_estado_usuario(estado_actual_usuario)

    return user_responses, estado_actual_usuario
