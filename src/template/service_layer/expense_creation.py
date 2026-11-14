"""Create an expense and fire everything that follows from it.

One function, two callers: the `POST /groups/{id}/expenses/` router and the confirmation of a
quick-capture draft. A draft must land through exactly the same path as a form, otherwise the two
would drift (archiving, notifications, push) the way the notification call sites once did.
"""

from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from template.domain.models.member import Member
from template.domain.models.repository import ExpenseRepository
from template.domain.schemas.expense import ExpenseCreate, ExpenseResponse
from template.service_layer.expense_service import ExpenseService
from template.service_layer.group_service import GroupService
from template.service_layer.member_service import MemberService
from template.service_layer.notification_service import NotificationService
from template.service_layer.push_service import PushService


# pylint: disable=too-many-arguments
def create_expense_with_effects(
    *,
    service: ExpenseService,
    expense_data: ExpenseCreate,
    creator: Member,
    background_tasks: BackgroundTasks,
    member_service: MemberService,
    group_service: GroupService,
    repository: ExpenseRepository,
    db: Session,
) -> ExpenseResponse:
    """Create the expense, refresh archived state, schedule notifications, build the response.

    Raises ValueError exactly as `ExpenseService.create_expense` does (e.g. a settled month).
    """
    expense = service.create_expense(expense_data)
    # A new expense can put an archived member back into debt, which must bring the group
    # back into their list — otherwise archiving would hide a balance from them.
    group_service.refresh_archived_state(service.group_id, repository)

    # Notify only the members of this expense's group
    members = service.get_members()
    group_name = service.get_group_name()
    multi_group_ids = service.get_multi_group_member_ids(members)

    # Add notification task to background tasks (skip for personal groups)
    if not service.is_personal_group():
        background_tasks.add_task(
            NotificationService().notify_expense_created,
            expense=expense,
            members=members,
            creator=creator,
            member_service=member_service,
            group_name=group_name,
            multi_group_member_ids=multi_group_ids,
            group_id=service.group_id,
            push_service=PushService(db),
        )

    return ExpenseResponse(
        id=expense.id,
        description=expense_data.description,
        amount=expense_data.amount,
        date=expense_data.date,
        category=expense_data.category.name,
        payer_id=expense_data.payer_id,
        installments=expense_data.installments,
        installment_no=1,
        payment_type=expense_data.payment_type,
        split_strategy=expense_data.split_strategy,
        parent_expense_id=expense.parent_expense_id,
        currency=getattr(expense_data, "currency", "ARS"),
    )
