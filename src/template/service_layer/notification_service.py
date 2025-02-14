"""Notification service for sending notifications to members."""

import os
import re
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List

import certifi
import requests

from template.domain.models.enums import NotificationType
from template.domain.models.member import Member
from template.domain.models.models import Expense
from template.domain.models.split import PercentageSplit
from template.service_layer.expense_service import ExpenseService
from template.service_layer.whatsapp_service import (
    enviar_mensaje_whatsapp,
    get_payer_name_from_id,
    text_message,
)


class NotificationService:
    """Service for sending notifications to members."""

    def __init__(self):
        """Initialize notification service with configuration."""
        # Email configuration
        self.smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self.smtp_username = os.getenv("SMTP_USERNAME", "")
        self.smtp_password = os.getenv("SMTP_PASSWORD", "")

    async def notify_expense_created(
        self, expense: Expense, members: List[Member], creator: Member, service: ExpenseService
    ) -> None:
        """Notify members about a new expense based on their notification preferences."""
        message = self._create_expense_message(expense, creator, service)

        for member in members:
            if member.id == creator.id:
                continue  # Skip the creator

            if member.notification_preference == NotificationType.EMAIL:
                await self._send_email(member.email, "New Expense Added 🗂️", message)
            elif member.notification_preference == NotificationType.WHATSAPP and member.telephone:
                await self._send_whatsapp(member.telephone, message)
            else:
                print("No notification sent (preference is NONE)")

    async def _send_email(self, to_email: str, subject: str, message: str) -> None:
        """Send an email notification."""
        try:
            msg = MIMEMultipart()
            msg["From"] = self.smtp_username
            msg["To"] = to_email
            msg["Subject"] = subject
            msg.attach(MIMEText(message, "plain"))

            context = ssl.create_default_context(cafile=certifi.where())

            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls(context=context)
                server.login(self.smtp_username, self.smtp_password)
                server.send_message(msg)

            print(f"Email sent to {to_email}")
        except (smtplib.SMTPException, ssl.SSLError, ConnectionError) as e:
            print(f"Failed to send email to {to_email}: {str(e)}")

    async def _send_whatsapp(self, phone_number: str, message: str) -> None:
        """Send a WhatsApp notification."""
        message = "New Expense Added 🗂️\n\n" + message
        try:
            # Format the message data using the text_message helper
            message_data = text_message(phone_number, message)

            # Send the message using the WhatsApp service
            response = enviar_mensaje_whatsapp(message_data)

            if response.get("status_code") == 200:
                print(f"Sent WhatsApp message to {phone_number}")
            else:
                print(f"Failed to send WhatsApp message: {response.get('detail')}")

        except (requests.RequestException, ValueError, ConnectionError) as e:
            print(f"Failed to send WhatsApp message to {phone_number}: {str(e)}")

    def _create_expense_message(self, expense: Expense, creator: Member, service: ExpenseService) -> str:
        """Create a message summarizing the expense."""
        payer = get_payer_name_from_id(expense.payer_id, service)

        description = self._remove_installments_from_description(expense.description)

        summary = [
            f"📝 Resumen del gasto creado por {creator.name}:\n",
            f"💬 Descripción: {description}",
            f"💰 Monto: ${expense.amount * expense.installments:.2f}",
            f"📅 Fecha: {expense.date.strftime('%Y-%m-%d')}",
            f"📂 Categoría: {expense.category.name} {expense.category.get_category_emoji(expense.category.name)}",
            f"👤 Pagador: {payer}",
            f"💳 Método de pago: {expense.payment_type}",
        ]

        if expense.installments > 1:
            summary.append(f"📅 Cuotas: {expense.installments}")

        if isinstance(expense.split_strategy, PercentageSplit):
            summary.append("\n💹 *Porcentajes de división:*")
            for member_id, percentage in expense.split_strategy.percentages.items():
                member_name = get_payer_name_from_id(int(member_id), service)
                summary.append(f"- {member_name}: {percentage}%")

        return "\n".join(summary)

    def _remove_installments_from_description(self, description: str) -> str:
        """Remove the installment suffix from the description.
        i.e: "Gasto de prueba (1/2)" becomes "Gasto de prueba"
        """
        return re.sub(r"\s*\(\d+\/\d+\)\s*$", "", description)
