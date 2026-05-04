"""WhatsApp Cloud API client abstraction."""

import os
from typing import Any, Dict, Protocol, Tuple

import requests


class WhatsAppClient(Protocol):
    """Interface for sending WhatsApp messages and uploading media."""

    def send_message(self, data: str) -> Dict[str, Any]:
        """Send a pre-serialised JSON message payload."""

    def upload_media(self, file_path: str) -> Tuple[str, int]:
        """Upload a file and return (media_id, status_code)."""


class MetaWhatsAppClient:
    """Sends messages and uploads media via the Meta WhatsApp Cloud API."""

    def send_message(self, data: str) -> Dict[str, Any]:
        try:
            token = os.getenv("WHATSAPP_TOKEN")
            url = os.getenv("WHATSAPP_URL")
            if not token:
                raise ValueError("WHATSAPP_TOKEN is not set")
            if not url:
                raise ValueError("WHATSAPP_URL is not set")

            headers = {"Content-Type": "application/json", "Authorization": "Bearer " + token}
            response = requests.post(url, headers=headers, data=data, timeout=5)
            if response.status_code == 200:
                return {"detail": "mensaje enviado", "status_code": 200}
            return {"detail": "error al enviar mensaje", "status_code": response.status_code}
        except ValueError as e:
            return {"detail": "no enviado, value error: " + str(e)}
        except requests.exceptions.RequestException as e:
            return {"detail": "no enviado " + str(e)}

    def upload_media(self, file_path: str) -> Tuple[str, int]:
        try:
            token = os.getenv("WHATSAPP_TOKEN")
            url = os.getenv("WHATSAPP_URL_MEDIA")
            if not token:
                raise ValueError("WHATSAPP_TOKEN is not set")
            if not url:
                raise ValueError("WHATSAPP_URL_MEDIA is not set")

            headers = {"Authorization": "Bearer " + token}
            with open(file_path, "rb") as f:
                files = {"file": (file_path, f, "application/pdf", {"Expires": "0"})}
                resp = requests.post(
                    url,
                    data={"messaging_product": "whatsapp", "type": "application/pdf"},
                    files=files,
                    headers=headers,
                    timeout=5,
                )
            if resp.status_code == 200:
                return resp.json().get("id"), 200
            return "Error al enviar documento", resp.status_code
        except requests.exceptions.RequestException as e:
            return str(e), 403
