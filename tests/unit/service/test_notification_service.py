"""Tests for NotificationService email sending via Brevo."""

from datetime import date
from unittest.mock import MagicMock, patch

from template.domain.models.category import Category
from template.domain.models.enums import PaymentType
from template.domain.models.models import Expense
from template.domain.models.split import EqualSplit, ExactAmountsSplit, PercentageSplit
from template.service_layer.notification_service import NotificationService

BREVO_URL = "https://api.brevo.com/v3/smtp/email"


def _make_expense(split_strategy):
    cat = Category()
    cat.name = "comida"
    return Expense(
        description="test",
        amount=300.0,
        date=date(2025, 5, 1),
        category=cat,
        payer_id=1,
        payment_type=PaymentType.DEBIT,
        split_strategy=split_strategy,
    )


class TestIsInvolvedInExpense:
    """_is_involved_in_expense filters excluded members from notifications."""

    def setup_method(self):
        self.service = NotificationService()

    def test_equal_split_no_participant_ids_includes_all(self):
        expense = _make_expense(EqualSplit())
        assert self.service._is_involved_in_expense(expense, 1) is True
        assert self.service._is_involved_in_expense(expense, 3) is True

    def test_equal_split_with_participant_ids_excludes_absent_member(self):
        expense = _make_expense(EqualSplit(participant_ids=[1, 2]))
        assert self.service._is_involved_in_expense(expense, 1) is True
        assert self.service._is_involved_in_expense(expense, 2) is True
        assert self.service._is_involved_in_expense(expense, 3) is False

    def test_exact_split_excludes_zero_and_absent_members(self):
        expense = _make_expense(ExactAmountsSplit({1: 200.0, 2: 100.0}))
        assert self.service._is_involved_in_expense(expense, 1) is True
        assert self.service._is_involved_in_expense(expense, 2) is True
        assert self.service._is_involved_in_expense(expense, 3) is False

    def test_exact_split_zero_amount_excluded(self):
        expense = _make_expense(ExactAmountsSplit({1: 300.0, 2: 0.0}))
        assert self.service._is_involved_in_expense(expense, 2) is False

    def test_percentage_split_excludes_zero_and_absent_members(self):
        expense = _make_expense(PercentageSplit({1: 70.0, 2: 30.0}))
        assert self.service._is_involved_in_expense(expense, 1) is True
        assert self.service._is_involved_in_expense(expense, 3) is False


class TestSendEmailBrevo:
    def _service(self, api_key="brevo-test-key", from_email="noreply@example.com"):
        with patch.dict(
            "os.environ",
            {"BREVO_API_KEY": api_key, "BREVO_FROM_EMAIL": from_email},
        ):
            return NotificationService()

    def test_sends_post_to_brevo_with_correct_payload(self):
        """A configured service POSTs to the Brevo API with the right structure."""
        service = self._service()
        mock_response = MagicMock()
        mock_response.status_code = 201

        with patch("requests.post", return_value=mock_response) as mock_post:
            service._send_email("to@example.com", "Hello", "Body text")

        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        assert kwargs["url"] if "url" in kwargs else mock_post.call_args[0][0] == BREVO_URL
        payload = kwargs["json"]
        assert payload["to"][0]["email"] == "to@example.com"
        assert payload["sender"]["email"] == "noreply@example.com"
        assert payload["subject"] == "Hello"
        assert payload["textContent"] == "Body text"

    def test_skips_send_when_api_key_not_configured(self):
        """No HTTP call is made when BREVO_API_KEY is absent."""
        with patch.dict("os.environ", {}, clear=True):
            service = NotificationService()

        with patch("requests.post") as mock_post:
            service._send_email("to@example.com", "Subject", "Body")

        mock_post.assert_not_called()

    def test_brevo_http_error_does_not_propagate(self):
        """A non-2xx response is logged but does not raise."""
        service = self._service()
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.text = "Forbidden"

        with patch("requests.post", return_value=mock_response):
            service._send_email("to@example.com", "Subject", "Body")

    def test_brevo_request_exception_does_not_propagate(self):
        """A network error during the POST is swallowed."""
        import requests as req_lib

        service = self._service()
        with patch("requests.post", side_effect=req_lib.RequestException("timeout")):
            service._send_email("to@example.com", "Subject", "Body")

    def test_html_content_included_when_provided(self):
        """htmlContent is added to the payload when supplied."""
        service = self._service()
        mock_response = MagicMock()
        mock_response.status_code = 201

        with patch("requests.post", return_value=mock_response) as mock_post:
            service._send_email("to@example.com", "Hello", "Plain text", html_content="<b>HTML</b>")

        _, kwargs = mock_post.call_args
        payload = kwargs["json"]
        assert payload["htmlContent"] == "<b>HTML</b>"
        assert payload["textContent"] == "Plain text"

    def test_no_html_content_key_when_not_provided(self):
        """htmlContent is absent from payload when not supplied."""
        service = self._service()
        mock_response = MagicMock()
        mock_response.status_code = 201

        with patch("requests.post", return_value=mock_response) as mock_post:
            service._send_email("to@example.com", "Hello", "Plain text")

        _, kwargs = mock_post.call_args
        payload = kwargs["json"]
        assert "htmlContent" not in payload
