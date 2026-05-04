"""Fake WhatsApp client for use in tests."""

import json
from typing import Any, Dict, List, Tuple


class FakeWhatsAppClient:
    """Records send_message and upload_media calls instead of hitting the Meta API."""

    def __init__(self) -> None:
        self.sent_messages: List[Dict[str, Any]] = []
        self.uploaded_files: List[str] = []

    def send_message(self, data: str) -> Dict[str, Any]:
        self.sent_messages.append(json.loads(data))
        return {"detail": "mensaje enviado", "status_code": 200}

    def upload_media(self, file_path: str) -> Tuple[str, int]:
        self.uploaded_files.append(file_path)
        return "fake-media-id-001", 200

    # --- helpers for test assertions ---

    def texts_sent(self) -> List[str]:
        """Return plain text bodies from all sent text messages."""
        return [m["text"]["body"] for m in self.sent_messages if m.get("type") == "text"]

    def reset(self) -> None:
        self.sent_messages.clear()
        self.uploaded_files.clear()
