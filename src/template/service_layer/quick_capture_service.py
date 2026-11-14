"""Quick capture: a screenshot from the iOS shortcut becomes a draft, and the person decides.

Nothing is created without an explicit choice. A capture only stores a draft (with its image)
and answers with a summary and a menu; the expense exists once the person taps a group. An
image that cannot be read is kept as a pending draft too, so nothing taken from the phone is
lost.

**Confirm creates exactly one expense, even when called twice at once** (double tap, network
retry). The draft row is locked with ``SELECT ... FOR UPDATE`` and its status is checked inside
that transaction. The existing creation path commits internally (once per month it touches, to
release the month's lock), and that first commit would also release the draft's lock. So the
draft is marked ``confirmed`` and flushed *before* creating the expense: the first internal
commit persists the expense rows and the draft's new status together, and a confirm waiting on
the lock then sees ``confirmed`` and answers 409. When creation is refused before any commit
(a settled month, a credit expense in a one-time group) the transaction is rolled back and the
draft is back to ``pending`` with its image.
"""

import logging
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import BackgroundTasks, HTTPException, status
from sqlalchemy.orm import Session

from template.adapters.orm import ExpenseDraftModel
from template.adapters.repositories import (
    ExpenseDraftRepository,
    GroupRepository,
    MemberRepository,
    SQLAlchemyExpenseRepository,
)
from template.domain.models.category import Category
from template.domain.models.group import GroupType
from template.domain.models.member import Member
from template.domain.schemas.expense import (
    CategorySchema,
    ExpenseCreate,
    ExpenseResponse,
    SplitStrategySchema,
)
from template.domain.schemas.quick_capture import QuickCaptureAction, QuickCaptureResult
from template.service_layer.expense_creation import create_expense_with_effects
from template.service_layer.expense_draft_service import (
    build_expense_draft,
    validate_image,
)
from template.service_layer.expense_service import ExpenseService
from template.service_layer.group_service import GroupService
from template.service_layer.member_service import MemberService
from template.service_layer.push_service import PushService
from template.service_layer.quick_capture_text import (
    GroupCandidate,
    money_text,
    option_label,
    pending_push_body,
    pick_options,
    similar_warning,
    summary_text,
)

logger = logging.getLogger(__name__)

RANKING_WINDOW_DAYS = 90
PENDING = "pending"
CONFIRMED = "confirmed"
DISCARDED = "discarded"

UNREADABLE_SUMMARY = "Captura sin leer"
UNREADABLE_MESSAGE = "No pude leerla, quedó en borradores"
KEEP_LABEL = "Editar en la app"
DISCARD_LABEL = "Cancelar"
ALREADY_RESOLVED = "Ese borrador ya se resolvió"
GROUP_UNAVAILABLE = "Ese grupo no está disponible"
NOT_FOUND = "Borrador no encontrado"
NO_AMOUNT = "Ese borrador no tiene monto: completalo en la app"

PUSH_TITLE = "Jirens"
PUSH_URL = "/drafts"
PUSH_TAG = "drafts-pending"


def _normalise_payment_type(value: Optional[str]) -> str:
    return "credit" if (value or "").strip().lower() in ("credit", "credito", "crédito") else "debit"


def _normalise_currency(value: Optional[str]) -> str:
    return "USD" if (value or "").strip().upper() == "USD" else "ARS"


class QuickCaptureService:
    """Use cases behind the shortcut endpoints. Commits its own transactions."""

    def __init__(self, db: Session):
        self._db = db
        self._drafts = ExpenseDraftRepository(db)
        self._groups = GroupRepository(db)
        self._expenses = SQLAlchemyExpenseRepository(db)

    # ------------------------------------------------------------------ capture

    def capture(self, member: Member, image: bytes, mime: str) -> QuickCaptureResult:
        """Store and read a screenshot; answer the summary and the menu. Creates no expense."""
        draft, options = self._store_and_read(member, image, mime)
        if options is None:
            self.notify_pending(member.id)
            return QuickCaptureResult(
                draft_id=draft.id,
                status="unreadable",
                summary=UNREADABLE_SUMMARY,
                warning=None,
                actions=[],
                message=UNREADABLE_MESSAGE,
            )

        amount = float(draft.amount or 0)
        currency = draft.currency or "ARS"
        actions = [
            QuickCaptureAction(label=option_label(c, amount, currency), action="confirm", group_id=c.group_id)
            for c in options
        ]
        actions.append(QuickCaptureAction(label=KEEP_LABEL, action="keep"))
        actions.append(QuickCaptureAction(label=DISCARD_LABEL, action="discard"))
        return QuickCaptureResult(
            draft_id=draft.id,
            status="read",
            summary=summary_text(
                category=draft.category or "otros",
                description=draft.description or "",
                amount=amount,
                currency=currency,
                payment_type=draft.payment_type or "debit",
                installments=draft.installments or 1,
            ),
            warning=self._similar_warning(draft, options),
            actions=actions,
            message=None,
        )

    def _store_and_read(
        self, member: Member, image: bytes, mime: str
    ) -> tuple[ExpenseDraftModel, Optional[list[GroupCandidate]]]:
        """Validate, save the draft with its image, read it and fill it in.

        Returns the draft and its ranked group options, or None for options when the image
        could not be read (no amount). Shared by the shortcut and the app's "Dejar para después".
        """
        try:
            validate_image(image, mime)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

        # Committed before the (slow, fallible) read, so the image survives whatever happens next.
        draft = self._drafts.add(ExpenseDraftModel(member_id=member.id, status=PENDING, image=image, image_mime=mime))
        self._drafts.commit()

        try:
            read = build_expense_draft(image, mime)
        except ValueError as exc:
            logger.info("Quick capture draft %s unreadable: %s", draft.id, exc)
            read = None
        except Exception:  # pylint: disable=broad-except
            logger.exception("Quick capture draft %s: the image parser failed", draft.id)
            read = None

        if read is None:
            return draft, None

        payment_type = _normalise_payment_type(read.payment_type)
        category = read.category if read.category in Category.get_user_categories() else "otros"
        draft.amount = read.amount
        draft.description = (read.description or "").strip()[:255] or None
        draft.category = category
        draft.expense_date = read.date
        draft.payment_type = payment_type
        draft.installments = max(1, int(read.installments or 1)) if payment_type == "credit" else 1
        draft.currency = _normalise_currency(read.currency)
        draft.confidence = read.confidence

        if read.amount is None:
            self._drafts.commit()
            return draft, None

        options = pick_options(self._candidates(member, category), payment_type)
        draft.suggested_group_id = options[0].group_id if options else None
        self._drafts.commit()
        return draft, options

    def _candidates(self, member: Member, category: str) -> list[GroupCandidate]:
        """The member's non-archived groups (personal included), with recent-use counts."""
        # The personal group competes like any other, so make sure it exists.
        GroupService(self._groups).get_or_create_personal_group(member.id)
        since = date.today() - timedelta(days=RANKING_WINDOW_DAYS)
        recent = self._expenses.count_recent_expenses_by_group(member.id, since)
        same_category = self._expenses.count_recent_expenses_by_group(member.id, since, category=category)
        candidates = []
        for group in self._groups.list_for_member(member.id, include_personal=True):
            if group.id is None:
                continue
            candidates.append(
                GroupCandidate(
                    group_id=group.id,
                    name=group.name,
                    group_type=GroupType(group.group_type).value,
                    member_count=len(self._groups.list_members(group.id)),
                    recent_count=recent.get(group.id, 0),
                    category_count=same_category.get(group.id, 0),
                )
            )
        return candidates

    def _similar_warning(self, draft: ExpenseDraftModel, options: list[GroupCandidate]) -> Optional[str]:
        """The first likely duplicate across the offered groups. Informative, never blocking."""
        if draft.amount is None or draft.expense_date is None:
            return None
        for option in options:
            matches = ExpenseService(self._expenses, option.group_id, self._groups).find_similar_expenses(
                draft.expense_date.year,
                draft.expense_date.month,
                draft.amount,
                draft.description or "",
                draft.expense_date,
                draft.currency or "ARS",
            )
            if matches:
                match = matches[0]
                return similar_warning(match.description, match.amount, match.currency or "ARS")
        return None

    # ------------------------------------------------------------------ confirm

    def confirm(
        self, member: Member, draft_id: int, group_id: int, background_tasks: BackgroundTasks
    ) -> ExpenseResponse:
        """Turn a pending draft into an expense in `group_id`, through the normal creation path."""
        draft = self._drafts.get_owned_for_update(draft_id, member.id)
        if draft is None:
            self._db.rollback()
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)
        if draft.status != PENDING:
            self._db.rollback()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=ALREADY_RESOLVED)
        if draft.amount is None:
            self._db.rollback()
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=NO_AMOUNT)
        available = {g.id for g in self._groups.list_for_member(member.id, include_personal=True)}
        if group_id not in available:
            self._db.rollback()
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=GROUP_UNAVAILABLE)

        try:
            expense_data = ExpenseCreate(
                description=draft.description or "Gasto",
                amount=draft.amount,
                date=draft.expense_date or date.today(),
                category=CategorySchema(name=draft.category or "otros"),
                payer_id=member.id,
                payment_type=_normalise_payment_type(draft.payment_type),
                installments=draft.installments or 1,
                split_strategy=SplitStrategySchema(type="equal"),
                currency=_normalise_currency(draft.currency),
            )
        except ValueError as exc:
            self._db.rollback()
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

        # Marked before creating: the creation path's first commit persists this together with
        # the expense rows (see the module docstring for why).
        draft.status = CONFIRMED
        draft.resolved_at = datetime.utcnow()
        self._db.flush()

        group_service = GroupService(self._groups)
        try:
            response = create_expense_with_effects(
                service=ExpenseService(self._expenses, group_id=group_id, group_repo=self._groups),
                expense_data=expense_data,
                creator=member,
                background_tasks=background_tasks,
                member_service=MemberService(MemberRepository(self._db)),
                group_service=group_service,
                repository=self._expenses,
                db=self._db,
            )
        except ValueError as exc:
            self._db.rollback()
            code = status.HTTP_409_CONFLICT if "está saldado" in str(exc) else status.HTTP_400_BAD_REQUEST
            raise HTTPException(status_code=code, detail=str(exc)) from exc

        draft.expense_id = response.id
        draft.image = None
        self._drafts.commit()
        return response

    def confirmed_message(self, expense: ExpenseResponse, group_id: int) -> str:
        """Closing notification text: "Gasto creado · $5.000 · Fran y Guada"."""
        group = self._groups.get(group_id)
        if group is None or group.group_type == GroupType.PERSONAL:
            name = "Personal"
        else:
            name = group.name
        return f"Gasto creado · {money_text(expense.amount, expense.currency or 'ARS')} · {name}"

    # ------------------------------------------------------------ keep/discard

    def keep(self, member: Member, draft_id: int) -> None:
        """Leave the draft pending for the app, and remind through push."""
        draft = self._drafts.get_owned(draft_id, member.id)
        if draft is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)
        if draft.status == PENDING:
            self.notify_pending(member.id)

    def discard(self, member: Member, draft_id: int) -> None:
        """Drop a pending draft and its image. Discarding twice is a no-op."""
        draft = self._drafts.get_owned_for_update(draft_id, member.id)
        if draft is None:
            self._db.rollback()
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)
        if draft.status == DISCARDED:
            self._db.rollback()
            return
        if draft.status != PENDING:
            self._db.rollback()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=ALREADY_RESOLVED)
        draft.status = DISCARDED
        draft.image = None
        draft.resolved_at = datetime.utcnow()
        self._drafts.commit()

    # -------------------------------------------------------------------- push

    def notify_pending(self, member_id: int) -> None:
        """Push (only push, no mail) the list of pending drafts, replacing the previous one."""
        drafts = self._drafts.list_pending(member_id)
        if not drafts:
            return
        body = pending_push_body([(d.description or "", d.amount, d.currency or "ARS") for d in drafts])
        PushService(self._db).send_if_subscribed(member_id, PUSH_TITLE, body, PUSH_URL, tag=PUSH_TAG)
