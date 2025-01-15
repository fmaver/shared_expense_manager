"""Whatsapp Bot"""
import logging
import os
from collections import defaultdict

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse

from template.dependencies import get_expense_service  # Import the dependency
from template.service_layer.expense_service import ExpenseService
from template.service_layer.whatsapp_service import (
    administrar_chatbot,
    obtener_mensaje_whatsapp,
    replace_start,
)

load_dotenv()  # Load environment variables from .env file

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# import services
router = APIRouter()

# Almacenamiento en memoria para el estado actual
estado_actual: defaultdict[str, dict] = defaultdict(
    lambda: {
        "estado": "inicial",
        "expense_data": {
            "service": None,
            "description": None,
            "amount": None,
            "date": None,
            "category": None,
            "payer_id": None,
            "payment_type": None,
            "installments": 1,
            "split_strategy": None,
        },
    }
)  # Estado inicial por defecto


@router.get("/webhook", response_class=PlainTextResponse)
async def verificar_token(request: Request) -> str:
    """Verify token for webhook"""
    logger.info("Webhook verification attempt started")
    try:
        # Log all incoming query parameters
        query_params = dict(request.query_params)
        logger.info("Received query parameters: %s", query_params)

        # Extract specific query parameters
        token = query_params.get("hub.verify_token")
        challenge = query_params.get("hub.challenge")

        # Log extracted values
        logger.info("Extracted token: %s, challenge: %s", token, challenge)

        # Check the token and challenge
        if token == os.getenv("TOKEN") and challenge:
            logger.info("Token verified successfully. Returning challenge: %s", challenge)
            return challenge

        # Token mismatch or challenge missing
        logger.warning("Invalid token or missing challenge")
        raise HTTPException(status_code=403, detail="token incorrecto")
    except Exception as e:
        logger.error("Error verifying token: %s", str(e))
        raise HTTPException(status_code=403, detail=str(e)) from e


@router.post("/webhook")
async def recibir_mensajes(
    request: Request, service: ExpenseService = Depends(get_expense_service)
):  # Add service as a dependency
    """recieve messages"""
    try:
        print("recibiendo mensajes")
        body = await request.json()
        print("body: ", body)
        entry = body["entry"][0]
        changes = entry["changes"][0]
        value = changes["value"]
        message = value["messages"][0]
        number = replace_start(message["from"])
        message_id = message["id"]
        text = obtener_mensaje_whatsapp(message)

        estado_nuevo = administrar_chatbot(text, number, message_id, estado_actual[number], service)
        estado_actual[number] = estado_nuevo
        return "enviado"

    except KeyError as e:  # Catch specific exceptions
        return {"detail": "no enviado, missing key: " + str(e)}
    except ValueError as e:  # Catch specific exceptions
        return {"detail": "no enviado, value error: " + str(e)}
    except (HTTPException, TypeError) as e:  # Catch specific exceptions
        return {"detail": "no enviado " + str(e)}
