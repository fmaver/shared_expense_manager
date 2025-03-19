"""Notification service for sending notifications to members."""

import os
import re
import smtplib
import ssl
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, List

import certifi
import requests

from template.domain.models.enums import NotificationType
from template.domain.models.member import Member
from template.domain.models.models import Expense
from template.domain.models.split import PercentageSplit
from template.service_layer.member_service import MemberService
from template.service_layer.whatsapp_service import (
    enviar_mensaje_whatsapp,
    template_message,
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
        self, expense: Expense, members: List[Member], creator: Member, member_service: MemberService
    ) -> None:
        """Notify members about a new expense based on their notification preferences."""

        for member in members:
            if member.id == creator.id:
                continue  # Skip the creator

            if member.notification_preference == NotificationType.EMAIL:
                message = self._create_expense_message(expense, creator, member_service)
                await self._send_email(member.email, "Notificación de Gasto 🗂️", message)

            elif member.notification_preference == NotificationType.WHATSAPP and member.telephone:
                print(f"Sending WhatsApp notification to {member.telephone}")
                last_interacted_with_wpp = member_service.get_last_wpp_chat_time(member)
                time_now = datetime.now(timezone.utc)
                
                # Ensure last_interacted_with_wpp is timezone-aware
                if last_interacted_with_wpp and not last_interacted_with_wpp.tzinfo:
                    last_interacted_with_wpp = last_interacted_with_wpp.replace(tzinfo=timezone.utc)
                
                print(f"Last interaction: {last_interacted_with_wpp}")
                print(f"Time now: {time_now}")
                
                # Only calculate time difference if last_interacted_with_wpp exists
                time_difference_days = None
                if last_interacted_with_wpp:
                    time_difference_days = (time_now - last_interacted_with_wpp).days
                    print(f"Time difference: {time_difference_days} days")

                if last_interacted_with_wpp is None or time_difference_days > 1:
                    parameters = self._create_expense_template_parameters(expense, creator, member_service)
                    print("Sending template message")
                    await self._send_whatsapp_template(member.telephone, parameters)

                else:
                    message = self._create_expense_message(expense, creator, member_service)
                    print("Sending regular message")
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
        message = "📝 Notamos un nuevo Gasto\nA continuación puede ver un resumen👇\n\n" + message
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

    async def _send_whatsapp_template(self, phone_number: str, parameters: List[Dict[str, Any]]) -> None:
        """Send a WhatsApp notification using a template."""
        try:
            # Format the message data using the text_message helper
            message_data = template_message(phone_number, "expense_notification", "es_AR", parameters)

            # Send the message using the WhatsApp service
            response = enviar_mensaje_whatsapp(message_data)

            if response.get("status_code") == 200:
                print(f"Sent WhatsApp template message to {phone_number}")
            else:
                print(f"Failed to send WhatsApp template message: {response.get('detail')}")

        except (requests.RequestException, ValueError, ConnectionError) as e:
            print(f"Failed to send WhatsApp template message to {phone_number}: {str(e)}")

    def _create_expense_message(self, expense: Expense, creator: Member, member_service: MemberService) -> str:
        """Create a message summarizing the expense."""
        payer = member_service.get_member_name_by_id(expense.payer_id)

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
        else:
            summary.append("📅 Cuotas: -")

        if isinstance(expense.split_strategy, PercentageSplit):
            summary.append("\n💹 Porcentajes de división:")
            for member_id, percentage in expense.split_strategy.percentages.items():
                member_name = member_service.get_member_name_by_id(int(member_id))
                summary.append(f"- {member_name}: {percentage}%")

        return "\n".join(summary)

    def _remove_installments_from_description(self, description: str) -> str:
        """Remove the installment suffix from the description.
        i.e: "Gasto de prueba (1/2)" becomes "Gasto de prueba"
        """
        return re.sub(r"\s*\(\d+\/\d+\)\s*$", "", description)

    def _create_expense_template_parameters(
        self, expense: Expense, creator: Member, member_service: MemberService
    ) -> List[Dict[str, str]]:
        """Create template parameters for WhatsApp template notification.

        Args:
            expense: The expense to create the parameters for
            creator: The member who created the expense
            member_service: The member service instance

        Returns:
            List of parameters for the WhatsApp template
        """
        description = self._remove_installments_from_description(expense.description)
        payer = member_service.get_member_name_by_id(expense.payer_id)

        parameters = [
            {"type": "text", "parameter_name": "creator_name", "text": creator.name},
            {"type": "text", "parameter_name": "descripcion", "text": description},
            {"type": "text", "parameter_name": "monto", "text": f"{expense.amount * expense.installments:.2f}"},
            {"type": "text", "parameter_name": "fecha", "text": expense.date.strftime("%Y-%m-%d")},
            {
                "type": "text",
                "parameter_name": "categoria",
                "text": f"{expense.category.name} {expense.category.get_category_emoji(expense.category.name)}",
            },
            {"type": "text", "parameter_name": "pagador", "text": payer},
            {"type": "text", "parameter_name": "pago", "text": expense.payment_type},
            {
                "type": "text",
                "parameter_name": "cuotas",
                "text": str(expense.installments) if expense.installments > 1 else "-",
            },
        ]

        # Add division information
        division_text = ""
        if isinstance(expense.split_strategy, PercentageSplit):
            division_parts = []
            for member_id, percentage in expense.split_strategy.percentages.items():
                member_name = member_service.get_member_name_by_id(int(member_id))
                division_parts.append(f"{member_name}: {percentage}%")
            division_text = ", ".join(division_parts)

        parameters.append(
            {"type": "text", "parameter_name": "division", "text": division_text if division_text else "-"}
        )

        return parameters
