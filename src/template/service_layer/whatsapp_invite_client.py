"""WhatsApp invite client — sends group invitation messages via WhatsApp."""

from typing import List, Protocol, runtime_checkable


@runtime_checkable
class WhatsAppInviteClient(Protocol):
    def send_invitation(self, to_phone: str, inviter_name: str, group_name: str, claim_url: str) -> None:
        """Send a group invitation message to the given phone number."""
        ...


class MockWhatsAppInviteClient:
    """Records outbound invitation messages for testing and staging use.

    The production Meta app does not yet have an approved group_invitation template.
    This mock is the default until that template is live.
    """

    def __init__(self) -> None:
        self.messages: List[dict] = []

    def send_invitation(self, to_phone: str, inviter_name: str, group_name: str, claim_url: str) -> None:
        entry = {"to": to_phone, "inviter": inviter_name, "group": group_name, "url": claim_url}
        self.messages.append(entry)
        print(
            f"[MockWhatsAppInviteClient] Would send invitation to {to_phone}: "
            f"{inviter_name} invited you to '{group_name}'. Claim at: {claim_url}"
        )


class MetaWhatsAppInviteClient:
    """Placeholder for future Meta group_invitation template. Not yet approved."""

    def send_invitation(self, to_phone: str, inviter_name: str, group_name: str, claim_url: str) -> None:
        # TODO: replace with real Meta API call once the group_invitation template (es_AR) is approved.
        raise NotImplementedError(
            "MetaWhatsAppInviteClient: group_invitation template not yet approved by Meta. "
            "Use MockWhatsAppInviteClient until the template is live."
        )
