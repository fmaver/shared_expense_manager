"""WhatsApp invite client — sends group invitation messages via WhatsApp."""

from typing import List, Protocol, runtime_checkable

from template.service_layer.whatsapp_service import (
    enviar_mensaje_whatsapp,
    template_message,
)


@runtime_checkable
class WhatsAppInviteClient(Protocol):
    """Protocol for sending group invitation notifications via WhatsApp."""

    def send_invitation(self, to_phone: str, inviter_name: str, group_name: str, claim_url: str) -> None:
        """Send a group invitation message to the given phone number."""


class MockWhatsAppInviteClient:
    """Records outbound invitation messages for testing; use in staging/tests."""

    def __init__(self) -> None:
        self.messages: List[dict] = []

    def send_invitation(self, to_phone: str, inviter_name: str, group_name: str, claim_url: str) -> None:
        """Record the message and log it; no real WhatsApp delivery."""
        entry = {"to": to_phone, "inviter": inviter_name, "group": group_name, "url": claim_url}
        self.messages.append(entry)
        print(
            f"[MockWhatsAppInviteClient] Would send invitation to {to_phone}: "
            f"{inviter_name} invited you to '{group_name}'. Claim at: {claim_url}"
        )


class MetaWhatsAppInviteClient:
    """Sends group invitations via the approved 'group_invitation' Meta template."""

    def send_invitation(self, to_phone: str, inviter_name: str, group_name: str, claim_url: str) -> None:
        """Send the group_invitation template to the invitee's phone number.

        Template positional variables: {{1}} inviter_name, {{2}} group_name, {{3}} claim_url.
        """
        parameters = [
            {"type": "text", "text": inviter_name},
            {"type": "text", "text": group_name},
            {"type": "text", "text": claim_url},
        ]
        message_data = template_message(to_phone, "group_invitation", "es_AR", parameters)
        response = enviar_mensaje_whatsapp(message_data)
        if response.get("status_code") != 200:
            print(f"[MetaWhatsAppInviteClient] Failed to send to {to_phone}: {response.get('detail')}")
