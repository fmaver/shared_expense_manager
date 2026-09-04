"""A member with no email and no telephone must never be contacted.

Ghost members exist as a name inside a group and are not app users. Every notification
branch must therefore check that it actually has somewhere to send before sending.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from template.domain.models.enums import NotificationType
from template.domain.models.member import Member
from template.service_layer.notification_service import NotificationService


def _ghost(preference: NotificationType) -> Member:
    """A member tracked by name alone."""
    return Member(id=7, name="Guada", telephone=None, email=None, notification_preference=preference)


def _creator() -> Member:
    return Member(
        id=1,
        name="Fran",
        telephone="5411111111",
        email="fran@example.com",
        notification_preference=NotificationType.EMAIL,
    )


@pytest.mark.parametrize(
    "preference",
    [NotificationType.EMAIL, NotificationType.WHATSAPP, NotificationType.NONE],
)
def test_ghost_member_is_never_contacted(preference):
    """Whatever the preference says, there is nowhere to send — so nothing is sent.

    EMAIL is the interesting case: the branch keys off the preference, and a ghost member
    whose preference is EMAIL would otherwise be handed to _send_email with email=None.
    """
    service = NotificationService()
    expense = MagicMock()
    expense.category.name = "comida"

    with (
        patch.object(service, "_send_email") as send_email,
        patch.object(service, "_send_wpp_expense_notification", new=AsyncMock()) as send_wpp,
        patch.object(service, "_is_involved_in_expense", return_value=True),
    ):
        asyncio.run(
            service.notify_expense_created(
                expense=expense,
                members=[_ghost(preference)],
                creator=_creator(),
                member_service=MagicMock(),
            )
        )

    send_email.assert_not_called()
    send_wpp.assert_not_called()
