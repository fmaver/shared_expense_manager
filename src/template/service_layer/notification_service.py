"""Notification service for sending notifications to members."""

import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List

import requests

from template.domain.models.enums import NotificationType
from template.domain.models.member import Member
from template.domain.models.models import Expense
from template.domain.models.split import EqualSplit, ExactAmountsSplit, PercentageSplit
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
        self.brevo_api_key = os.getenv("BREVO_API_KEY", "")
        self.brevo_from_email = os.getenv("BREVO_FROM_EMAIL", "")

    async def notify_expense_created(
        self, expense: Expense, members: List[Member], creator: Member, member_service: MemberService
    ) -> None:
        """Notify members about a new expense based on their notification preferences."""

        for member in members:
            if member.id == creator.id:
                continue  # Skip the creator

            if not self._is_involved_in_expense(expense, member.id):
                continue  # Skip members excluded from this expense

            if member.notification_preference == NotificationType.EMAIL:
                message = self._create_expense_message(expense, creator, member_service)
                self._send_email(member.email, "Notificación de Gasto 🗂️", message)

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

                if last_interacted_with_wpp is None or (time_difference_days is not None and time_difference_days >= 1):
                    parameters = self._create_expense_template_parameters(expense, creator, member_service)
                    print("Sending template message")
                    await self._send_whatsapp_template(member.telephone, parameters)

                else:
                    message = self._create_expense_message(expense, creator, member_service)
                    print("Sending regular message")
                    await self._send_whatsapp(member.telephone, message)

            else:
                print("No notification sent (preference is NONE)")

    def send_invitation_email(self, to_email: str, inviter_name: str, group_name: str, claim_url: str) -> None:
        """Send a group invitation email via Brevo."""
        subject = f"📨 {inviter_name} te invitó al grupo '{group_name}'"
        text_body = (
            f"Hola!\n\n"
            f"{inviter_name} te invitó al grupo '{group_name}' en Shared Expenses.\n\n"
            f"Aceptá la invitación entrando a este enlace:\n{claim_url}\n\n"
            f"El enlace vence en 7 días. Si no esperabas esta invitación, podés ignorar este mensaje."
        )
        html_body = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin:0;padding:0;background:#f0f2f5;font-family:Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="padding:40px 0;">
    <tr><td align="center">
      <table width="520" cellpadding="0" cellspacing="0"
        style="background:#ffffff;border-radius:10px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08);">
        <!-- Header -->
        <tr>
          <td style="background:#4f46e5;padding:32px 40px;text-align:center;">
            <p style="margin:0;font-size:28px;">💸</p>
            <h1 style="margin:8px 0 0;color:#ffffff;font-size:22px;font-weight:700;">Shared Expenses</h1>
          </td>
        </tr>
        <!-- Body -->
        <tr>
          <td style="padding:36px 40px;">
            <h2 style="margin:0 0 16px;font-size:20px;color:#1a1a2e;">¡Fuiste invitado!</h2>
            <p style="margin:0 0 12px;font-size:15px;color:#444;line-height:1.6;">
              <strong>{inviter_name}</strong> te invitó a unirte al grupo
              <strong style="color:#4f46e5;">"{group_name}"</strong>.
            </p>
            <p style="margin:0 0 28px;font-size:15px;color:#444;line-height:1.6;">
              Hacé clic en el botón de abajo para aceptar la invitación y crear tu cuenta:
            </p>
            <table cellpadding="0" cellspacing="0">
              <tr>
                <td style="border-radius:6px;background:#4f46e5;">
                  <a href="{claim_url}"
                    style="display:inline-block;padding:14px 32px;color:#ffffff;
                    font-size:15px;font-weight:700;text-decoration:none;border-radius:6px;">
                    Aceptar invitación →
                  </a>
                </td>
              </tr>
            </table>
          </td>
        </tr>
        <!-- Footer -->
        <tr>
          <td style="padding:20px 40px 32px;border-top:1px solid #f0f0f0;">
            <p style="margin:0 0 8px;font-size:12px;color:#999;line-height:1.5;">
              Este enlace vence en <strong>7 días</strong>. Si no esperabas esta invitación, podés ignorar este mensaje.
            </p>
            <p style="margin:0;font-size:12px;color:#bbb;">
              Si el botón no funciona, copiá este enlace en tu navegador:<br>
              <a href="{claim_url}" style="color:#4f46e5;word-break:break-all;">{claim_url}</a>
            </p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""
        self._send_email(to_email, subject, text_body, html_content=html_body)

    def _send_email(self, to_email: str, subject: str, message: str, html_content: str | None = None) -> None:
        """Send an email notification via Brevo HTTP API."""
        if not self.brevo_api_key or not self.brevo_from_email:
            print("Brevo not configured (BREVO_API_KEY / BREVO_FROM_EMAIL unset), skipping email")
            return

        payload = {
            "sender": {"email": self.brevo_from_email},
            "to": [{"email": to_email}],
            "subject": subject,
            "textContent": message,
        }
        if html_content:
            payload["htmlContent"] = html_content
        headers = {
            "api-key": self.brevo_api_key,
            "Content-Type": "application/json",
        }
        try:
            response = requests.post(
                "https://api.brevo.com/v3/smtp/email",
                json=payload,
                headers=headers,
                timeout=10,
            )
            if response.status_code in (200, 201, 202):
                print(f"Email sent to {to_email}")
            else:
                print(f"Failed to send email to {to_email}: {response.status_code} {response.text}")
        except requests.RequestException as e:
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

    def _is_involved_in_expense(self, expense: Expense, member_id: int) -> bool:
        """Return True if a member has a non-zero share in this expense."""
        strategy = expense.split_strategy
        if isinstance(strategy, EqualSplit):
            if strategy.participant_ids is None:
                return True
            return member_id in strategy.participant_ids
        if isinstance(strategy, ExactAmountsSplit):
            return strategy.amounts.get(member_id, 0.0) > 0
        if isinstance(strategy, PercentageSplit):
            return strategy.percentages.get(member_id, 0.0) > 0
        return True

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
        elif isinstance(expense.split_strategy, ExactAmountsSplit):
            summary.append("\n💵 Montos asignados:")
            for member_id, amount_val in expense.split_strategy.amounts.items():
                member_name = member_service.get_member_name_by_id(int(member_id))
                summary.append(f"- {member_name}: ${amount_val:.2f}")
        elif isinstance(expense.split_strategy, EqualSplit):
            if expense.split_strategy.participant_ids:
                names = [
                    member_service.get_member_name_by_id(mid) or str(mid)
                    for mid in expense.split_strategy.participant_ids
                ]
                summary.append(f"\n💡 División equitativa entre: {', '.join(names)}")
            else:
                summary.append("\n💡 División Equitativa")

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
                division_parts.append(f"- {member_name}: {percentage}%")
            division_text = ", ".join(division_parts)
        elif isinstance(expense.split_strategy, ExactAmountsSplit):
            division_parts = []
            for member_id, amount_val in expense.split_strategy.amounts.items():
                member_name = member_service.get_member_name_by_id(int(member_id))
                division_parts.append(f"- {member_name}: ${amount_val:.2f}")
            division_text = ", ".join(division_parts)
        elif isinstance(expense.split_strategy, EqualSplit):
            if expense.split_strategy.participant_ids:
                names = [
                    member_service.get_member_name_by_id(mid) or str(mid)
                    for mid in expense.split_strategy.participant_ids
                ]
                division_text = f"Equitativo entre: {', '.join(names)}"
            else:
                division_text = "División Equitativa"

        parameters.append(
            {"type": "text", "parameter_name": "division", "text": division_text if division_text else "-"}
        )

        return parameters
