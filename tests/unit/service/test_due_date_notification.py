"""El aviso de vencimiento usa el mismo ruteo que todo lo demás: push, y si no, mail."""

import asyncio
from datetime import date
from unittest.mock import MagicMock, patch

from template.domain.models.enums import NotificationType
from template.domain.models.member import Member
from template.service_layer.notification_service import NotificationService
from template.service_layer.push_service import push_body_for_due_date


def _member(member_id: int, name: str) -> Member:
    return Member(
        id=member_id,
        name=name,
        telephone=None,
        email=f"{name.lower()}@example.com",
        notification_preference=NotificationType.EMAIL,
    )


def _ghost() -> Member:
    return Member(id=9, name="Tomi", telephone=None, email=None, notification_preference=NotificationType.EMAIL)


def _push(subscribed_ids):
    service = MagicMock()
    service.send_if_subscribed.side_effect = lambda member_id, *_: member_id in subscribed_ids
    return service


class TestPushBody:
    def test_it_names_the_service_and_the_days_left(self):
        assert push_body_for_due_date("Luz", date(2026, 10, 20), 3) == "📅 Luz vence en 3 días (20/10)"

    def test_zero_days_reads_as_today_rather_than_in_0_days(self):
        assert push_body_for_due_date("Luz", date(2026, 10, 20), 0) == "📅 Luz vence hoy (20/10)"

    def test_one_day_is_singular(self):
        assert push_body_for_due_date("Luz", date(2026, 10, 20), 1) == "📅 Luz vence mañana (20/10)"


class TestRouting:
    def test_push_replaces_email_for_subscribed_members(self):
        service = NotificationService()
        push_service = _push({1})

        with patch.object(service, "_send_email") as send_email:
            asyncio.run(
                service.notify_due_date(
                    due_date_label="Luz",
                    due_on=date(2026, 10, 20),
                    days_before=3,
                    members=[_member(1, "Fran"), _member(2, "Guada")],
                    group_name="Depto",
                    group_id=4,
                    push_service=push_service,
                )
            )

        assert [c.args[0] for c in send_email.call_args_list] == ["guada@example.com"]

    def test_ghost_members_are_never_contacted(self):
        service = NotificationService()

        with patch.object(service, "_send_email") as send_email:
            asyncio.run(
                service.notify_due_date(
                    due_date_label="Luz",
                    due_on=date(2026, 10, 20),
                    days_before=3,
                    members=[_ghost()],
                    group_name="Depto",
                    group_id=4,
                )
            )

        send_email.assert_not_called()
