"""Fake WhatsApp client for use in tests."""

import json
from typing import Any, Dict, List, Tuple


class FakeWhatsAppClient:
    """Records send_message, upload_media and download_media calls instead of hitting the Meta API."""

    def __init__(self) -> None:
        self.sent_messages: List[Dict[str, Any]] = []
        self.uploaded_files: List[str] = []
        # Map media_id → (bytes, mime_type) for download_media stubs
        self.media_store: Dict[str, Tuple[bytes, str]] = {}

    def send_message(self, data: str) -> Dict[str, Any]:
        """Record the message payload and return a success response."""
        self.sent_messages.append(json.loads(data))
        return {"detail": "mensaje enviado", "status_code": 200}

    def upload_media(self, file_path: str) -> Tuple[str, int]:
        """Record the file path and return a fake media ID."""
        self.uploaded_files.append(file_path)
        return "fake-media-id-001", 200

    def download_media(self, media_id: str) -> Tuple[bytes, str]:
        """Return pre-seeded bytes for a media ID, or empty bytes."""
        if media_id in self.media_store:
            return self.media_store[media_id]
        return b"", "image/jpeg"

    def texts_sent(self) -> List[str]:
        """Return plain text bodies from all sent text messages."""
        return [m["text"]["body"] for m in self.sent_messages if m.get("type") == "text"]

    def reset(self) -> None:
        """Clear recorded calls."""
        self.sent_messages.clear()
        self.uploaded_files.clear()
        self.media_store.clear()
