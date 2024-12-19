"""wpp service"""
import json
import os
import re
import time
from datetime import datetime
from typing import Any, Collection, Dict, Optional

import requests

from template.domain.models.enums import PaymentType
from template.domain.models.models import MonthlyShare
from template.domain.models.pdf_builder import ExpensePDF
from template.domain.schemas.expense import (
    CategorySchema,
    ExpenseCreate,
    SplitStrategySchema,
)
from template.service_layer.expense_service import ExpenseService


def obtener_mensaje_whatsapp(message):
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


def obtener_media_id(file_path):
    """get media id"""
    try:
        whatsapp_token = os.getenv("WHATSAPP_TOKEN")
        url = os.getenv("WHATSAPP_URL_MEDIA")

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


def enviar_mensaje_whatsapp(data):
    """send message"""
    try:
        whatsapp_token = os.getenv("WHATSAPP_TOKEN")
        whatsapp_url = os.getenv("WHATSAPP_URL")
        headers = {"Content-Type": "application/json", "Authorization": "Bearer " + whatsapp_token}
        print("se envia ", data)
        response = requests.post(whatsapp_url, headers=headers, data=data, timeout=5)

        # Log the response
        print("WhatsApp API response:", response.status_code, response.text)

        if response.status_code == 200:
            return "mensaje enviado", 200
        return "error al enviar mensaje", response.status_code
    except ValueError as e:
        return {"detail": "no enviado, value error: " + str(e)}
    except (requests.exceptions.HTTPException, TypeError) as e:
        return {"detail": "no enviado " + str(e)}


def text_message(number, text):
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


def button_reply_message(number, options, body, footer, sedd):
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


def list_reply_message(number, options, body, footer, sedd):
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


def document_message(number, media_id, caption, filename):
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


def image_message(url):
    """image message"""
    data = json.dumps(
        {"messaging_product": "whatsapp", "recipient_type": "individual", "type": "image", "image": {"link": url}}
    )
    return data


def sticker_message(number, sticker_id):
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


def reply_reaction_message(number, message_id, emoji):
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


def reply_text_message(number, message_id, text):
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


def mark_read_message(message_id):
    """clavar visto"""
    data = json.dumps({"messaging_product": "whatsapp", "status": "read", "message_id": message_id})
    return data


# pylint: disable=too-many-branches, too-many-statements
def administrar_chatbot(text, number, message_id, estado_actual_usuario, service: ExpenseService):  # noqa: C901
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
        responses, estado_actual_usuario = handle_settle_accounts(number, estado_actual_usuario, message_id, service)
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

    elif estado_actual_usuario["estado"] == "esperando_pagador" and text.lower() in ["fran", "guadi"]:
        responses, estado_actual_usuario = handle_waiting_for_payer(number, estado_actual_usuario, message_id, text)
        user_responses.extend(responses)

    elif estado_actual_usuario["estado"] == "esperando_fecha_pago" and re.match(r"^\d{2}-\d{2}-\d{4}$", text):
        responses, estado_actual_usuario = handle_waiting_for_payment_date(
            number, estado_actual_usuario, text, service, message_id
        )
        user_responses.extend(responses)

    elif estado_actual_usuario["estado"] == "esperando_categoria":
        responses, estado_actual_usuario = handle_waiting_for_category(number, estado_actual_usuario, text)
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

    else:
        data = text_message(number, "Lo siento, no entendí lo que dijiste.")
        user_responses.append(data)

    for item in user_responses:
        print("enviando...", item)
        enviar_mensaje_whatsapp(item)

    return estado_actual_usuario  # noqa: C901


def create_expense(estado_actual_usuario, service, split_strategy_dict):
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
def replace_start(s):
    """replace starting number"""
    number = s[3:]
    if s.startswith("521"):
        return "52" + number
    if s.startswith("549"):
        return "54" + number
    return s


def clean_estado_usuario(estado_actual_usuario):
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


def handle_greetings(number, estado_actual_usuario):
    """handle greetings"""
    user_responses = []

    body = "¡Hola! Bienvenido a F&G Expenses. ¿Cómo podemos ayudarte hoy?"
    footer = "Fran y Guadi"
    options = ["Cargar Gasto", "Prestar Plata", "Generar Balance"]

    reply_button_data = button_reply_message(number, options, body, footer, "sed1")

    user_responses.append(reply_button_data)

    # Siempre que volvemos al estado inicial, reseteamos el estado del usuario
    estado_actual_usuario = clean_estado_usuario(estado_actual_usuario)

    return user_responses, estado_actual_usuario


def handle_document_request(number, estado_actual_usuario, service: ExpenseService):
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

    caption = f"Balance de Fran Y Guadi para la fecha de {month_year.month}/{month_year.year}"

    document_data = document_message(number, media_id, caption, filename)
    user_responses.append(document_data)
    print("enviando documento...")

    return user_responses, estado_actual_usuario


def handle_balance_request(number, estado_actual_usuario, message_id):
    """handle balance"""
    user_responses = []

    estado_actual_usuario["expense_data"]["service"] = "generar balance"

    body = "Genial! Indica el mes y año para calcular el balance con el formato MM-AAAA"
    reply_text = reply_text_message(number, message_id, body)
    user_responses.append(reply_text)

    estado_actual_usuario["estado"] = "esperando_fecha_balance"

    return user_responses, estado_actual_usuario


def handle_settle_accounts(number, estado_actual_usuario, message_id, service: ExpenseService):
    """handle settle shares"""
    user_responses = []

    fecha = estado_actual_usuario["expense_data"]["date"]
    month_year = datetime.strptime(fecha, "%m-%Y")
    print("saldando cuentas para el mes y año: ", str(month_year.month), str(month_year.year))

    monthly_share_settled = service.settle_monthly_share(month_year.year, month_year.month)
    print(f"monthly_share_settled with balance: {monthly_share_settled.balances}")

    # Llamar al método settle_monthly_share del servicio
    try:
        body = "Cuentas saldadas. Deseas hacer algo mas?"
        options = ["Ir al Inicio", "No gracias", "Obtener Documento"]
        footer = "Fran y Guadi"

        reply_button_data = button_reply_message(number, options, body, footer, "sed1")
        user_responses.append(reply_button_data)

    except ValueError as e:
        print("Error al saldar cuentas: ", e)
        body = str(e)
        reply_text = reply_text_message(number, message_id, body)
        user_responses.append(reply_text)

    return user_responses, estado_actual_usuario


def handle_waiting_for_balance_date(number, estado_actual_usuario, text, service: ExpenseService):
    """handle waiting for payment date"""
    user_responses = []

    def process_balance(month_year):
        monthly_balance = service.get_monthly_balance(month_year.year, month_year.month)
        if isinstance(monthly_balance, MonthlyShare):
            return monthly_balance
        return None

    def generate_balance_message(monthly_balance, month_year):
        balances_message = f"Balances de gastos para {month_year.month}/{month_year.year}:\n"
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
            options = ["Obtener Documento", "Saldar Cuentas", "Ir al Inicio"]
            reply_button_data = button_reply_message(number, options, body, "Fran y Guadi", "sed1")
            user_responses.append(reply_button_data)
        else:
            user_responses.append(text_message(number, "No se encontraron gastos para el mes y año seleccionados."))

        return user_responses, estado_actual_usuario

    except ValueError:
        user_responses.append(
            text_message(number, "El formato ingresado no es válido. Por favor, intenta de nuevo con MM-AAAA.")
        )
        return user_responses, estado_actual_usuario


def handle_lending_money(number, estado_actual_usuario, message_id):
    """handle lend money"""
    user_responses = []

    estado_actual_usuario["expense_data"]["service"] = "prestar plata"

    body = "Perfecto! Por favor, indicanos el monto que deseas prestar"
    reply_text = reply_text_message(number, message_id, body)
    user_responses.append(reply_text)

    estado_actual_usuario["estado"] = "esperando_monto"

    return user_responses, estado_actual_usuario


def handle_loading_expense(number, estado_actual_usuario, message_id):
    """handle loading expense"""
    user_responses = []

    estado_actual_usuario["expense_data"]["service"] = "cargar gasto"

    body = "Perfecto! Por favor, indicanos el monto del gasto"
    reply_text = reply_text_message(number, message_id, body)
    user_responses.append(reply_text)

    estado_actual_usuario["estado"] = "esperando_monto"

    return user_responses, estado_actual_usuario


def handle_waiting_for_amount(number, estado_actual_usuario, message_id, text):
    """handle waiting for amount"""
    user_responses = []
    print("esperando_monto")
    try:
        amount = float(text)
        estado_actual_usuario["expense_data"]["amount"] = amount

        body = "Genial! Ahora por favor proporciona una breve descripción del consumo."
        reply_text = reply_text_message(number, message_id, body)
        user_responses.append(reply_text)

        estado_actual_usuario["estado"] = "esperando_descripcion"

    except ValueError:
        error_message = text_message(number, "El monto ingresado no es válido. Por favor, intenta de nuevo.")
        user_responses.append(error_message)

    return user_responses, estado_actual_usuario


def handle_waiting_for_description(number, estado_actual_usuario, text):
    """handle wiaitng for desc"""
    user_responses = []
    if estado_actual_usuario["expense_data"]["service"] == "cargar gasto":
        estado_actual_usuario["expense_data"]["description"] = text.lower()
        body = "Genial! Ahora por favor indica quién realizó el gasto"
    else:
        estado_actual_usuario["expense_data"]["description"] = f"Prestamo: {text.lower()}"
        body = "Genial! Ahora por favor indica quien realizó el prestamo"

    footer = "Fran y Guadi"
    options = ["Fran", "Guadi"]

    estado_actual_usuario["estado"] = "esperando_pagador"
    reply_button_data = button_reply_message(number, options, body, footer, "sed1")
    user_responses.append(reply_button_data)

    return user_responses, estado_actual_usuario


def handle_waiting_for_payer(number, estado_actual_usuario, message_id, text):
    """handle waiting for payer"""
    user_responses = []
    estado_actual_usuario["expense_data"]["payer_id"] = (
        1 if text.lower() == "fran" else 2
    )  # revisar si es la mejor forma de hacerlo

    body = "Por favor, proporciona la fecha del consumo en el formato DD-MM-AAAA."
    reply_text = reply_text_message(number, message_id, body)
    user_responses.append(reply_text)

    estado_actual_usuario["estado"] = "esperando_fecha_pago"

    return user_responses, estado_actual_usuario


def handle_waiting_for_payment_date(number, estado_actual_usuario, text, service: ExpenseService, message_id):
    """handle waiting for payment date"""
    user_responses = []
    try:
        date = datetime.strptime(text, "%d-%m-%Y").date()
        estado_actual_usuario["expense_data"]["date"] = date

        # SI ES UN PRESTAMO, LUEGO DE LA FECHA YA PODEMOS CARGARLO ##
        if estado_actual_usuario["expense_data"]["service"] == "prestar plata":
            print("cargando el prestamo...")
            id_of_not_payer = (
                1 if estado_actual_usuario["expense_data"]["payer_id"] == 2 else 2
            )  # ver si esto es lo mejor

            split_strategy_dict = {
                "type": "percentage",
                "percentages": {estado_actual_usuario["expense_data"]["payer_id"]: 0, id_of_not_payer: 100},
            }
            estado_actual_usuario["expense_data"]["payment_type"] = "debito"
            estado_actual_usuario["expense_data"]["category"] = "prestamo"

            ######################################
            create_expense(estado_actual_usuario, service, split_strategy_dict=split_strategy_dict)
            ######################################

            body = "Excelente! Préstamo guardado. Podemos ayudarte con algo más?"
            options = ["Ir al inicio", "No gracias"]

            reply_button_data = button_reply_message(number, options, body, "Fran y Guadi", "sed1")
            user_responses.append(reply_button_data)

        else:
            body = "A que categoria pertenece?\n Comida - Auto - Casa - Mascota - Compras - Salida - Shopping - Otro"
            reply_text = reply_text_message(number, message_id, body)
            user_responses.append(reply_text)

            estado_actual_usuario["estado"] = "esperando_categoria"

    except ValueError as e:
        print(e)
        error_message = text_message(number, str(e))
        user_responses.append(error_message)

    return user_responses, estado_actual_usuario


def handle_waiting_for_category(number, estado_actual_usuario, text):
    """handle waiting for category"""
    user_responses = []
    print("esperando_categoria")
    estado_actual_usuario["expense_data"]["category"] = text.lower()

    body = "Recibido! Ahora, elige un tipo de pago:"
    footer = "Fran y Guadi"
    options = ["Crédito", "Débito"]

    reply_button_data = button_reply_message(number, options, body, footer, "sed1")
    user_responses.append(reply_button_data)

    estado_actual_usuario["estado"] = "esperando_tipo_pago"

    return user_responses, estado_actual_usuario


def handle_waiting_for_payment_type(number, estado_actual_usuario, message_id, text):
    """handle waiting for payment"""
    user_responses = []

    print("esperando_tipo_pago")
    estado_actual_usuario["expense_data"]["payment_type"] = text.lower()

    if text.lower() == "crédito":
        body = "Por favor, indica la cantidad de cuotas: "
        reply_text = reply_text_message(number, message_id, body)
        user_responses.append(reply_text)
        estado_actual_usuario["estado"] = "esperando_cuotas"
    else:
        body = "Por favor, elige una estrategia de división: "
        footer = "Fran y Guadi"
        options = ["Equitativamente", "Porcentaje"]

        reply_button_data = button_reply_message(number, options, body, footer, "sed1")
        user_responses.append(reply_button_data)

        estado_actual_usuario["estado"] = "esperando_estrategia"

    return user_responses, estado_actual_usuario


def handle_waiting_for_installments(number, estado_actual_usuario, text):
    """handle waiting for installments"""
    user_responses = []

    print("esperando_cuotas")
    try:
        estado_actual_usuario["expense_data"]["installments"] = int(text)

        body = "Por favor, elige una estrategia de división: "
        footer = "Fran y Guadi"
        options = ["Equitativamente", "Porcentaje"]

        reply_button_data = button_reply_message(number, options, body, footer, "sed1")
        user_responses.append(reply_button_data)

        estado_actual_usuario["estado"] = "esperando_estrategia"

    except ValueError:
        error_message = text_message(
            number, "La cantidad de cuotas ingresada no es válida. Por favor, intenta de nuevo."
        )
        user_responses.append(error_message)

    return user_responses, estado_actual_usuario


def handle_waiting_for_split_strategy(number, estado_actual_usuario, message_id, text, service: ExpenseService):
    """handle waiting for split"""
    user_responses = []

    print("esperando_estrategia")
    estado_actual_usuario["expense_data"]["split_strategy"] = text.lower()

    if text.lower() == "porcentaje":
        body = "Por favor, indica el porcentaje del valor del pagador, sin simbolos."
        reply_text = reply_text_message(number, message_id, body)
        user_responses.append(reply_text)
        estado_actual_usuario["estado"] = "esperando_porcentaje"

    else:
        strategy_dict: Dict[str, Optional[Collection[Any]]] = {
            "type": "equal",
            "percentages": None,
        }

        ######################################
        create_expense(estado_actual_usuario, service, split_strategy_dict=strategy_dict)
        ######################################

        body = "Excelente! Gasto guardado. Podemos ayudarte con algo más?"
        options = ["Ir al inicio", "No gracias"]
        footer = "Fran y Guadi"

        reply_button_data = button_reply_message(number, options, body, footer, "sed1")
        user_responses.append(reply_button_data)

    return user_responses, estado_actual_usuario


def handle_waiting_for_percentage(number, estado_actual_usuario, text, service):
    """handle waiting for percentage"""
    user_responses = []
    print("esperando_porcentaje")
    try:
        payer_percentage = float(text)
        id_of_not_payer = 1 if estado_actual_usuario["expense_data"]["payer_id"] == 2 else 2  # ver si esto es lo mejor

        split_strategy_dictionary = {
            "type": "percentage",
            "percentages": {
                estado_actual_usuario["expense_data"]["payer_id"]: payer_percentage,
                id_of_not_payer: 100 - payer_percentage,
            },
        }
        print("porcentaje: ", payer_percentage)

        ######################################
        create_expense(estado_actual_usuario, service, split_strategy_dict=split_strategy_dictionary)
        ######################################

        body = "Excelente! Gasto guardado. Podemos ayudarte con algo más?"
        options = ["Ir al inicio", "No gracias"]
        footer = "Fran y Guadi"

        reply_button_data = button_reply_message(number, options, body, footer, "sed1")
        user_responses.append(reply_button_data)

    except ValueError:
        error_message = text_message(number, "El porcentaje ingresado no es válido. Por favor, intenta de nuevo.")
        user_responses.append(error_message)

    return user_responses, estado_actual_usuario


def handle_no_thanks(number, estado_actual_usuario, message_id):
    """handle goodbye"""
    user_responses = []

    body = "Gracias por usar F&G Expenses. Estamos aquí para ayudarte cuando lo necesites."
    reply_text = reply_text_message(number, message_id, body)
    user_responses.append(reply_text)

    # Siempre que terminemos una conversación, reseteamos el estado del usuario
    estado_actual_usuario = clean_estado_usuario(estado_actual_usuario)

    return user_responses, estado_actual_usuario
