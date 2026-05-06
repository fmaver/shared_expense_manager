"""Tests for NotificationService email sending via SendGrid."""

import asyncio
from unittest.mock import MagicMock, patch

from template.service_layer.notification_service import NotificationService

SENDGRID_URL = "https://api.sendgrid.com/v3/mail/send"


class TestSendEmailSendGrid:
    def _service(self, api_key="sg-test-key", from_email="noreply@example.com"):
        with patch.dict(
            "os.environ",
            {"SENDGRID_API_KEY": api_key, "SENDGRID_FROM_EMAIL": from_email},
        ):
            return NotificationService()

    def test_sends_post_to_sendgrid_with_correct_payload(self):
        """A configured service POSTs to the SendGrid API with the right structure."""
        service = self._service()
        mock_response = MagicMock()
        mock_response.status_code = 202

        with patch("requests.post", return_value=mock_response) as mock_post:
            asyncio.run(service._send_email("to@example.com", "Hello", "Body text"))

        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        payload = kwargs["json"]
        assert payload["personalizations"][0]["to"][0]["email"] == "to@example.com"
        assert payload["from"]["email"] == "noreply@example.com"
        assert payload["subject"] == "Hello"
        assert payload["content"][0]["value"] == "Body text"

    def test_skips_send_when_api_key_not_configured(self):
        """No HTTP call is made when SENDGRID_API_KEY is absent."""
        with patch.dict("os.environ", {}, clear=True):
            service = NotificationService()

        with patch("requests.post") as mock_post:
            asyncio.run(service._send_email("to@example.com", "Subject", "Body"))

        mock_post.assert_not_called()

    def test_sendgrid_http_error_does_not_propagate(self):
        """A non-2xx response is logged but does not raise."""
        service = self._service()
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.text = "Forbidden"

        with patch("requests.post", return_value=mock_response):
            asyncio.run(service._send_email("to@example.com", "Subject", "Body"))

    def test_sendgrid_request_exception_does_not_propagate(self):
        """A network error during the POST is swallowed."""
        import requests as req_lib

        service = self._service()
        with patch("requests.post", side_effect=req_lib.RequestException("timeout")):
            asyncio.run(service._send_email("to@example.com", "Subject", "Body"))
