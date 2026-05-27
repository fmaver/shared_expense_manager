"""Notification service for sending notifications to members."""

import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests

from template.domain.models.enums import NotificationType
from template.domain.models.formatters import format_amount_es
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

    async def notify_expense_created(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        expense: Expense,
        members: List[Member],
        creator: Member,
        member_service: MemberService,
        group_name: Optional[str] = None,
        multi_group_member_ids: Optional[set] = None,
    ) -> None:
        """Notify members about a new expense based on their notification preferences."""
        is_loan = expense.category and expense.category.name.lower() == "prestamo"
        subject = "💰 Nuevo préstamo" if is_loan else "💸 Nuevo gasto registrado"

        for member in members:
            if member.id == creator.id:
                continue

            if not self._is_involved_in_expense(expense, member.id):
                continue

            effective_group = (
                group_name if (group_name and multi_group_member_ids and member.id in multi_group_member_ids) else None
            )

            if member.notification_preference == NotificationType.EMAIL:
                message = self._create_expense_message(expense, creator, member_service)
                if effective_group:
                    message = f"📁 *{effective_group}*\n\n{message}"
                html = self._build_html_expense_created(expense, creator, member_service, group_name=effective_group)
                self._send_email(member.email, subject, message, html_content=html)

            elif member.notification_preference == NotificationType.WHATSAPP and member.telephone:
                await self._send_wpp_expense_notification(member, expense, creator, member_service, effective_group)

            else:
                print("No notification sent (preference is NONE)")

    async def _send_wpp_expense_notification(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        member: Member,
        expense: Expense,
        creator: Member,
        member_service: MemberService,
        effective_group: Optional[str],
    ) -> None:
        print(f"Sending WhatsApp notification to {member.telephone}")
        last_interacted = member_service.get_last_wpp_chat_time(member)
        time_now = datetime.now(timezone.utc)

        if last_interacted and not last_interacted.tzinfo:
            last_interacted = last_interacted.replace(tzinfo=timezone.utc)

        if last_interacted is None or (time_now - last_interacted).days >= 1:
            print("Sending template message")
            await self._send_whatsapp_template(
                member.telephone,
                self._create_expense_template_parameters(expense, creator, member_service),
            )
        else:
            message = self._create_expense_message(expense, creator, member_service)
            if effective_group:
                message = f"📁 *{effective_group}*\n\n{message}"
            print("Sending regular message")
            await self._send_whatsapp(member.telephone, message)

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
            message_data = text_message(phone_number, message)
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
            message_data = template_message(phone_number, "expense_notification", "es_AR", parameters)
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
        """Create a plain-text message summarizing the expense."""
        payer = member_service.get_member_name_by_id(expense.payer_id)

        if expense.category and expense.category.name.lower() == "prestamo":
            return (
                f"💸 *{payer}* te prestó *${format_amount_es(expense.amount)}*"
                f" el {expense.date.strftime('%d/%m/%Y')}.\n\n"
                f"_Saldo actualizado disponible en la app._"
            )

        description = self._remove_installments_from_description(expense.description)

        summary = [
            f"📝 Resumen del gasto creado por {creator.name}:\n",
            f"💬 Descripción: {description}",
            f"💰 Monto: ${expense.amount * expense.installments:.2f}",
            f"📅 Fecha: {expense.date.strftime('%d/%m/%Y')}",
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

    # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
    async def notify_expense_updated(
        self,
        old: Expense,
        new: Expense,
        actor: Member,
        members: List[Member],
        member_service: MemberService,
        group_name: Optional[str] = None,
        multi_group_member_ids: Optional[set] = None,
    ) -> None:
        """Notify members (union of old+new involved, minus actor) about an edited expense."""
        actor_name = member_service.get_member_name_by_id(actor.id) or actor.name
        old_is_loan = old.category and old.category.name.lower() == "prestamo"
        new_is_loan = new.category and new.category.name.lower() == "prestamo"
        is_loan = old_is_loan or new_is_loan

        if is_loan:
            message = (
                f"✏️ *{actor_name}* editó un préstamo.\n"
                f"Antes: ${format_amount_es(old.amount)} el {old.date.strftime('%d/%m/%Y')}\n"
                f"Ahora: ${format_amount_es(new.amount)} el {new.date.strftime('%d/%m/%Y')}"
            )
        else:
            old_cat = old.category.name if old.category else "-"
            new_cat = new.category.name if new.category else "-"
            old_desc = self._remove_installments_from_description(old.description)
            new_desc = self._remove_installments_from_description(new.description)
            message = (
                f"✏️ *{actor_name}* editó un gasto.\n"
                f"Antes: {old_desc} · ${format_amount_es(old.amount)} · "
                f"{old.date.strftime('%d/%m/%Y')} · {old_cat}\n"
                f"Ahora: {new_desc} · ${format_amount_es(new.amount)} · "
                f"{new.date.strftime('%d/%m/%Y')} · {new_cat}"
            )

        subject = "✏️ Préstamo actualizado" if is_loan else "✏️ Gasto actualizado"
        recipients = {
            m
            for m in members
            if m.id != actor.id and (self._is_involved_in_expense(old, m.id) or self._is_involved_in_expense(new, m.id))
        }
        # Include group name in HTML when at least one recipient needs it
        html_group = (
            group_name if (multi_group_member_ids and multi_group_member_ids & {m.id for m in recipients}) else None
        )
        html = self._build_html_expense_updated(old, new, actor_name, member_service, group_name=html_group)
        await self._broadcast(
            message,
            recipients,
            member_service,
            subject=subject,
            html_content=html,
            group_name=group_name,
            multi_group_member_ids=multi_group_member_ids,
        )

    async def notify_expense_deleted(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        expense: Expense,
        actor: Member,
        members: List[Member],
        member_service: MemberService,
        group_name: Optional[str] = None,
        multi_group_member_ids: Optional[set] = None,
    ) -> None:
        """Notify involved members (minus actor) that an expense was deleted."""
        actor_name = member_service.get_member_name_by_id(actor.id) or actor.name
        is_loan = expense.category and expense.category.name.lower() == "prestamo"

        if is_loan:
            message = (
                f"🗑️ *{actor_name}* eliminó un préstamo de "
                f"${format_amount_es(expense.amount)} del {expense.date.strftime('%d/%m/%Y')}."
            )
        else:
            cat = expense.category.name if expense.category else "-"
            desc = self._remove_installments_from_description(expense.description)
            message = (
                f"🗑️ *{actor_name}* eliminó el gasto: {desc} · "
                f"${format_amount_es(expense.amount)} · {expense.date.strftime('%d/%m/%Y')} · {cat}."
            )

        subject = "🗑️ Préstamo eliminado" if is_loan else "🗑️ Gasto eliminado"
        recipients = {m for m in members if m.id != actor.id and self._is_involved_in_expense(expense, m.id)}
        html_group = (
            group_name if (multi_group_member_ids and multi_group_member_ids & {m.id for m in recipients}) else None
        )
        html = self._build_html_expense_deleted(expense, actor_name, member_service, group_name=html_group)
        await self._broadcast(
            message,
            recipients,
            member_service,
            subject=subject,
            html_content=html,
            group_name=group_name,
            multi_group_member_ids=multi_group_member_ids,
        )

    async def _broadcast(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        message: str,
        recipients,
        member_service: MemberService,
        subject: str = "Actualización de Gasto 📝",
        html_content: str | None = None,
        group_name: Optional[str] = None,
        multi_group_member_ids: Optional[set] = None,
    ) -> None:
        """Send a message to each recipient per their notification preference."""
        for member in recipients:
            show_group = bool(group_name and multi_group_member_ids and member.id in multi_group_member_ids)
            if member.notification_preference == NotificationType.EMAIL:
                self._send_email(member.email, subject, message, html_content=html_content)
            elif member.notification_preference == NotificationType.WHATSAPP and member.telephone:
                last_interacted = member_service.get_last_wpp_chat_time(member)
                time_now = datetime.now(timezone.utc)
                if last_interacted and not last_interacted.tzinfo:
                    last_interacted = last_interacted.replace(tzinfo=timezone.utc)
                days_since = (time_now - last_interacted).days if last_interacted else None
                if last_interacted is None or (days_since is not None and days_since >= 1):
                    print(f"Skipping WPP notification for {member.telephone}: outside 24h window")
                else:
                    wa_message = f"📁 *{group_name}*\n\n{message}" if show_group else message
                    await self._send_whatsapp(member.telephone, wa_message)

    def _remove_installments_from_description(self, description: str) -> str:
        """Remove the installment suffix from the description."""
        return re.sub(r"\s*\(\d+\/\d+\)\s*$", "", description)

    def _split_description(self, expense: Expense, member_service: MemberService) -> str:
        """Return a short text summary of the split strategy."""
        strategy = expense.split_strategy
        if isinstance(strategy, PercentageSplit):
            parts = [
                f"{member_service.get_member_name_by_id(int(mid)) or mid}: {pct}%"
                for mid, pct in strategy.percentages.items()
            ]
            return ", ".join(parts)
        if isinstance(strategy, ExactAmountsSplit):
            parts = [
                f"{member_service.get_member_name_by_id(int(mid)) or mid}: ${amt:.2f}"
                for mid, amt in strategy.amounts.items()
            ]
            return ", ".join(parts)
        if isinstance(strategy, EqualSplit) and strategy.participant_ids:
            names = [member_service.get_member_name_by_id(mid) or str(mid) for mid in strategy.participant_ids]
            return f"Equitativo ({', '.join(names)})"
        return "Equitativo"

    def _expense_detail_rows(
        self, expense: Expense, member_service: MemberService, group_name: Optional[str] = None
    ) -> List[Tuple[str, str]]:
        """Build label/value row pairs for an expense summary."""
        payer = member_service.get_member_name_by_id(expense.payer_id) or "—"
        desc = self._remove_installments_from_description(expense.description)
        cat_name = expense.category.name if expense.category else "—"
        cat_emoji = expense.category.get_category_emoji(cat_name) if expense.category else ""
        rows: List[Tuple[str, str]] = []
        if group_name:
            rows.append(("Grupo", group_name))
        rows += [
            ("Descripción", desc),
            ("Monto", f"${format_amount_es(expense.amount)}"),
            ("Fecha", expense.date.strftime("%d/%m/%Y")),
            ("Categoría", f"{cat_name} {cat_emoji}".strip()),
            ("Pagador", payer),
            ("Pago", expense.payment_type),
        ]
        if expense.installments > 1:
            rows.append(("Cuotas", str(expense.installments)))
        rows.append(("División", self._split_description(expense, member_service)))
        return rows

    def _html_card(self, emoji: str, title: str, body_html: str, footer_note: str = "") -> str:
        """Wrap body_html in the standard card layout."""
        footer_row = ""
        if footer_note:
            footer_row = (
                '<tr><td style="padding:20px 40px 32px;border-top:1px solid #f0f0f0;">'
                f'<p style="margin:0;font-size:12px;color:#999;line-height:1.5;">{footer_note}</p>'
                "</td></tr>"
            )
        return f"""<!DOCTYPE html>
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
        <tr>
          <td style="background:#4f46e5;padding:32px 40px;text-align:center;">
            <p style="margin:0;font-size:28px;">{emoji}</p>
            <h1 style="margin:8px 0 0;color:#ffffff;font-size:22px;font-weight:700;">Shared Expenses</h1>
          </td>
        </tr>
        <tr>
          <td style="padding:36px 40px;">
            <h2 style="margin:0 0 20px;font-size:20px;color:#1a1a2e;">{title}</h2>
            {body_html}
          </td>
        </tr>
        {footer_row}
      </table>
    </td></tr>
  </table>
</body>
</html>"""

    def _html_detail_table(self, rows: List[Tuple[str, str]]) -> str:
        """Render a two-column label/value table."""
        rows_html = "".join(
            f"<tr>"
            f'<td style="padding:7px 16px 7px 0;font-size:14px;color:#666;'
            f'white-space:nowrap;vertical-align:top;">{label}</td>'
            f'<td style="padding:7px 0;font-size:14px;color:#1a1a2e;font-weight:600;">{value}</td>'
            f"</tr>"
            for label, value in rows
        )
        return f'<table cellpadding="0" cellspacing="0" width="100%">{rows_html}</table>'

    def _build_html_expense_created(
        self, expense: Expense, creator: Member, member_service: MemberService, group_name: Optional[str] = None
    ) -> str:
        """Build HTML for a new-expense or new-loan notification email."""
        payer = member_service.get_member_name_by_id(expense.payer_id) or "—"
        is_loan = expense.category and expense.category.name.lower() == "prestamo"

        if is_loan:
            rows: List[Tuple[str, str]] = []
            if group_name:
                rows.append(("Grupo", group_name))
            rows += [
                ("Prestador", payer),
                ("Monto", f"${format_amount_es(expense.amount)}"),
                ("Fecha", expense.date.strftime("%d/%m/%Y")),
            ]
            intro = (
                f'<p style="margin:0 0 16px;font-size:15px;color:#444;line-height:1.6;">'
                f"<strong>{payer}</strong> registró un nuevo préstamo.</p>"
            )
            return self._html_card(
                "💰",
                "Nuevo préstamo",
                intro + self._html_detail_table(rows),
                footer_note="El saldo actualizado está disponible en la app.",
            )

        rows = self._expense_detail_rows(expense, member_service, group_name=group_name)
        intro = (
            f'<p style="margin:0 0 16px;font-size:15px;color:#444;line-height:1.6;">'
            f"<strong>{creator.name}</strong> registró un nuevo gasto.</p>"
        )
        return self._html_card("💸", "Nuevo gasto registrado", intro + self._html_detail_table(rows))

    def _build_html_expense_updated(  # pylint: disable=too-many-locals,too-many-arguments,too-many-positional-arguments
        self,
        old: Expense,
        new: Expense,
        actor_name: str,
        member_service: MemberService,
        group_name: Optional[str] = None,
    ) -> str:
        """Build HTML for an expense-updated notification email."""
        old_is_loan = old.category and old.category.name.lower() == "prestamo"
        new_is_loan = new.category and new.category.name.lower() == "prestamo"
        is_loan = old_is_loan or new_is_loan
        title = "Préstamo actualizado" if is_loan else "Gasto actualizado"

        if is_loan:
            old_rows: List[Tuple[str, str]] = []
            new_rows: List[Tuple[str, str]] = []
            if group_name:
                old_rows.append(("Grupo", group_name))
            old_rows += [
                ("Monto", f"${format_amount_es(old.amount)}"),
                ("Fecha", old.date.strftime("%d/%m/%Y")),
            ]
            new_rows += [
                ("Monto", f"${format_amount_es(new.amount)}"),
                ("Fecha", new.date.strftime("%d/%m/%Y")),
            ]
        else:
            old_rows = self._expense_detail_rows(old, member_service, group_name=group_name)
            new_rows = self._expense_detail_rows(new, member_service)

        kind = "préstamo" if is_loan else "gasto"
        intro = (
            f'<p style="margin:0 0 20px;font-size:15px;color:#444;line-height:1.6;">'
            f"<strong>{actor_name}</strong> editó un {kind}.</p>"
        )
        before_header = (
            '<div style="background:#fef2f2;border-radius:6px;padding:16px;margin-bottom:12px;">'
            '<p style="margin:0 0 10px;font-size:11px;font-weight:700;color:#dc2626;'
            'text-transform:uppercase;letter-spacing:.5px;">Antes</p>'
        )
        before_box = before_header + self._html_detail_table(old_rows) + "</div>"
        after_header = (
            '<div style="background:#f0fdf4;border-radius:6px;padding:16px;">'
            '<p style="margin:0 0 10px;font-size:11px;font-weight:700;color:#16a34a;'
            'text-transform:uppercase;letter-spacing:.5px;">Después</p>'
        )
        after_box = after_header + self._html_detail_table(new_rows) + "</div>"
        return self._html_card("✏️", title, intro + before_box + after_box)

    def _build_html_expense_deleted(
        self, expense: Expense, actor_name: str, member_service: MemberService, group_name: Optional[str] = None
    ) -> str:
        """Build HTML for an expense-deleted notification email."""
        is_loan = expense.category and expense.category.name.lower() == "prestamo"
        title = "Préstamo eliminado" if is_loan else "Gasto eliminado"
        kind = "préstamo" if is_loan else "gasto"

        if is_loan:
            payer = member_service.get_member_name_by_id(expense.payer_id) or "—"
            rows: List[Tuple[str, str]] = []
            if group_name:
                rows.append(("Grupo", group_name))
            rows += [
                ("Prestador", payer),
                ("Monto", f"${format_amount_es(expense.amount)}"),
                ("Fecha", expense.date.strftime("%d/%m/%Y")),
            ]
        else:
            rows = self._expense_detail_rows(expense, member_service, group_name=group_name)

        intro = (
            f'<p style="margin:0 0 16px;font-size:15px;color:#444;line-height:1.6;">'
            f"<strong>{actor_name}</strong> eliminó el siguiente {kind}:</p>"
        )
        deleted_box = '<div style="background:#fef2f2;border-radius:6px;padding:16px;">'
        deleted_box += self._html_detail_table(rows) + "</div>"
        return self._html_card("🗑️", title, intro + deleted_box)

    def _create_expense_template_parameters(  # pylint: disable=too-many-locals
        self, expense: Expense, creator: Member, member_service: MemberService
    ) -> List[Dict[str, str]]:
        """Create template parameters for WhatsApp template notification."""
        payer = member_service.get_member_name_by_id(expense.payer_id)
        is_loan = expense.category and expense.category.name.lower() == "prestamo"
        description = (
            f"Préstamo de {payer}" if is_loan else self._remove_installments_from_description(expense.description)
        )
        creator_label = f"{payer} te prestó" if is_loan else creator.name

        parameters = [
            {"type": "text", "parameter_name": "creator_name", "text": creator_label},
            {"type": "text", "parameter_name": "descripcion", "text": description},
            {"type": "text", "parameter_name": "monto", "text": f"{expense.amount * expense.installments:.2f}"},
            {"type": "text", "parameter_name": "fecha", "text": expense.date.strftime("%d/%m/%Y")},
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
