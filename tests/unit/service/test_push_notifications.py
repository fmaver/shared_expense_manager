"""Web push delivery and channel routing — in-memory SQLite.

Push reaches only members who installed the app to their home screen, so it *replaces* the
channel for those members rather than adding to it: everyone else keeps getting email, which is
what stops anyone losing coverage when WhatsApp free-form replies end.
"""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from template.adapters.orm import Base, MemberModel, PushSubscriptionModel
from template.adapters.repositories import PushSubscriptionRepository
from template.domain.models.enums import NotificationType
from template.service_layer.push_service import PushService, resolve_channel

MEMBER_ID = 1
OTHER_ID = 2


@pytest.fixture(autouse=True)
def vapid_key():
    """send_to_member returns early without a key — correct in production, so tests supply one."""
    with patch.dict("os.environ", {"VAPID_PRIVATE_KEY": "test-private-key"}):
        yield


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as s:
        yield s


@pytest.fixture()
def populated_session(session):
    session.add_all(
        [
            MemberModel(
                id=MEMBER_ID,
                name="Fran",
                email="fran@example.com",
                hashed_password="h",
                notification_preference=NotificationType.EMAIL,
            ),
            MemberModel(
                id=OTHER_ID,
                name="Guada",
                email="guada@example.com",
                hashed_password="h",
                notification_preference=NotificationType.EMAIL,
            ),
        ]
    )
    session.commit()
    return session


def _subscribe(session, member_id: int, endpoint: str = "https://push.example/abc"):
    return PushSubscriptionRepository(session).save(member_id=member_id, endpoint=endpoint, p256dh="key", auth="auth")


# ---------------------------------------------------------------------------
# Which channel a member gets
# ---------------------------------------------------------------------------


def test_a_member_with_a_subscription_gets_push(populated_session):
    _subscribe(populated_session, MEMBER_ID)
    repo = PushSubscriptionRepository(populated_session)

    assert resolve_channel(_member(populated_session, MEMBER_ID), repo) == "push"


def test_a_member_without_a_subscription_keeps_email(populated_session):
    """The whole point of the fallback: not installing must not mean silence."""
    repo = PushSubscriptionRepository(populated_session)

    assert resolve_channel(_member(populated_session, MEMBER_ID), repo) == NotificationType.EMAIL


def test_registering_a_device_overrides_a_none_preference(populated_session):
    """Tapping "turn on" and granting the permission prompt IS the opt-in.

    NONE is also the column default, so honouring it over a fresh subscription would have made
    push look broken on most accounts.
    """
    member = _member(populated_session, MEMBER_ID)
    member.notification_preference = NotificationType.NONE
    populated_session.commit()
    _subscribe(populated_session, MEMBER_ID)
    repo = PushSubscriptionRepository(populated_session)

    assert resolve_channel(member, repo) == "push"


def test_none_still_silences_a_member_with_no_device(populated_session):
    """The opt-out keeps working for the channels it actually governs."""
    member = _member(populated_session, MEMBER_ID)
    member.notification_preference = NotificationType.NONE
    populated_session.commit()
    repo = PushSubscriptionRepository(populated_session)

    assert resolve_channel(member, repo) == NotificationType.NONE


def test_one_members_subscription_does_not_affect_another(populated_session):
    _subscribe(populated_session, MEMBER_ID)
    repo = PushSubscriptionRepository(populated_session)

    assert resolve_channel(_member(populated_session, OTHER_ID), repo) == NotificationType.EMAIL


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------


def test_sends_to_every_device_a_member_registered(populated_session):
    """Phone plus laptop is normal, which is why subscriptions are a table not a column."""
    _subscribe(populated_session, MEMBER_ID, "https://push.example/phone")
    _subscribe(populated_session, MEMBER_ID, "https://push.example/laptop")

    with patch("template.service_layer.push_service.webpush") as send:
        PushService(populated_session).send_to_member(MEMBER_ID, "Nuevo gasto", "Coto $4.500", "/groups/1")

    assert send.call_count == 2


def test_a_gone_subscription_is_deleted(populated_session):
    """410 Gone is how a browser says the subscription is dead — keeping it would retry forever."""
    _subscribe(populated_session, MEMBER_ID)

    with patch("template.service_layer.push_service.webpush", side_effect=_web_push_error(410)):
        PushService(populated_session).send_to_member(MEMBER_ID, "t", "b", "/")

    assert populated_session.query(PushSubscriptionModel).count() == 0


def test_a_transient_failure_keeps_the_subscription(populated_session):
    """A 500 is the push service having a bad day, not the device going away."""
    _subscribe(populated_session, MEMBER_ID)

    with patch("template.service_layer.push_service.webpush", side_effect=_web_push_error(500)):
        PushService(populated_session).send_to_member(MEMBER_ID, "t", "b", "/")

    assert populated_session.query(PushSubscriptionModel).count() == 1


def test_sending_to_a_member_with_no_devices_is_a_no_op(populated_session):
    with patch("template.service_layer.push_service.webpush") as send:
        PushService(populated_session).send_to_member(MEMBER_ID, "t", "b", "/")

    send.assert_not_called()


def test_one_dead_device_does_not_stop_the_others(populated_session):
    """A stale laptop subscription must not cost the user the notification on their phone."""
    _subscribe(populated_session, MEMBER_ID, "https://push.example/dead")
    _subscribe(populated_session, MEMBER_ID, "https://push.example/alive")

    with patch(
        "template.service_layer.push_service.webpush",
        side_effect=[_gone_exception(410), None],
    ) as send:
        PushService(populated_session).send_to_member(MEMBER_ID, "t", "b", "/")

    assert send.call_count == 2
    assert populated_session.query(PushSubscriptionModel).count() == 1


# ---------------------------------------------------------------------------
# Subscriptions
# ---------------------------------------------------------------------------


def test_resubscribing_the_same_endpoint_does_not_duplicate(populated_session):
    """Browsers re-send the same endpoint; a second row would double every notification."""
    _subscribe(populated_session, MEMBER_ID, "https://push.example/same")
    _subscribe(populated_session, MEMBER_ID, "https://push.example/same")

    assert populated_session.query(PushSubscriptionModel).count() == 1


def _member(session, member_id: int) -> MemberModel:
    return session.get(MemberModel, member_id)


def _gone_exception(status: int):
    """A WebPushException carrying an HTTP status, shaped like the ones pywebpush raises."""
    from pywebpush import WebPushException

    response = MagicMock()
    response.status_code = status
    return WebPushException("push failed", response=response)


def _web_push_error(status: int):
    """Callable form, for when the whole call should raise."""

    def _raise(*_args, **_kwargs):
        raise _gone_exception(status)

    return _raise


# ---------------------------------------------------------------------------
# What the notification says and where it goes
# ---------------------------------------------------------------------------


def test_the_deep_link_carries_the_month_of_the_expense():
    """An expense in another month is not on the screen the group opens to.

    Without the month the notification would land the user on the group and leave them
    hunting for the very thing it was about.
    """
    from datetime import date

    from template.service_layer.push_service import push_url_for_expense

    expense = MagicMock()
    expense.id = 42
    expense.date = date(2026, 5, 10)

    url = push_url_for_expense(expense, group_id=7)

    assert url == "/groups/7?year=2026&month=5&expense=42"


def test_the_body_says_who_what_and_how_much():
    """Enough to decide whether it matters, without opening the app."""
    from template.service_layer.push_service import push_body_for_expense

    expense = MagicMock()
    expense.description = "Coto"
    expense.amount = 4500.0
    expense.currency = "ARS"
    expense.payer_id = 2

    member_service = MagicMock()
    member_service.get_member.return_value = MagicMock(name="x")
    member_service.get_member.return_value.name = "Guada"

    body = push_body_for_expense(expense, MagicMock(), member_service)

    assert body.startswith("Guada cargó Coto · $")


def test_a_usd_expense_is_not_shown_as_pesos():
    from template.service_layer.push_service import push_body_for_expense

    expense = MagicMock()
    expense.description = "Libro"
    expense.amount = 20.0
    expense.currency = "USD"
    expense.payer_id = 2
    member_service = MagicMock()
    member_service.get_member.return_value.name = "Fran"

    body = push_body_for_expense(expense, MagicMock(), member_service)

    assert "US$" in body


class TestSendIfSubscribed:
    """The channel-routing entry point: it must report whether it actually delivered.

    Callers fall through to email on False, so a wrong answer here silently drops a
    notification rather than sending it twice.
    """

    def test_returns_false_and_sends_nothing_without_a_device(self, populated_session):
        service = PushService(populated_session)

        with patch("template.service_layer.push_service.webpush") as webpush_mock:
            assert service.send_if_subscribed(MEMBER_ID, "Viaje", "cuerpo", "/groups/1") is False

        webpush_mock.assert_not_called()

    def test_returns_true_once_a_device_is_registered(self, populated_session):
        populated_session.add(
            PushSubscriptionModel(endpoint="https://push.example/1", p256dh="k", auth="a", member_id=MEMBER_ID)
        )
        populated_session.commit()
        service = PushService(populated_session)

        with patch("template.service_layer.push_service.webpush") as webpush_mock:
            assert service.send_if_subscribed(MEMBER_ID, "Viaje", "cuerpo", "/groups/1") is True

        webpush_mock.assert_called_once()
