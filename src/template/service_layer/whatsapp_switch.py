"""The single kill switch for every outbound WhatsApp message.

WhatsApp started charging per conversation, so it is off unless `WHATSAPP_ENABLED` says
otherwise — unset means off. Every send path (notifications, invitations, the chatbot) asks
`whatsapp_enabled()` rather than reading the variable itself, so turning it back on is one env
change and no code. The one deliberate exception while off is the chatbot's one-time notice
(`WHATSAPP_OFF_NOTICE`): the person just wrote, so the reply sits inside Meta's free 24-hour
window, and it is sent at most once per phone.

Read on every call, not at import time, so tests (and a Render env change plus restart) see the
current value.
"""

import os

_TRUTHY = ("1", "true", "yes", "on")

# Stored in `chat_sessions.estado` once the notice went out, so later messages get no reply.
# A plain string in an existing String(50) column — no migration.
WHATSAPP_OFF_NOTICE_STATE = "whatsapp_off_notificado"


def whatsapp_enabled() -> bool:
    """True only when `WHATSAPP_ENABLED` is explicitly truthy."""
    return os.getenv("WHATSAPP_ENABLED", "false").strip().lower() in _TRUTHY


def whatsapp_off_notice() -> str:
    """The one message the chatbot still sends while WhatsApp is off."""
    app_url = os.getenv("APP_BASE_URL", "http://localhost:5173")
    return f"Hola 👋 El chat de WhatsApp ya no está disponible. Cargá tus gastos desde la app: {app_url}"
