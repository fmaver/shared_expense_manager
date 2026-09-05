"""Expense API endpoints."""

from datetime import date

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from sqlalchemy.orm import Session

from template.adapters.database import get_db
from template.adapters.repositories import PushSubscriptionRepository
from template.dependencies import (
    get_expense_service,
    get_group_service,
    get_member_service,
    get_repository,
)
from template.domain.models.enums import PaymentType
from template.domain.models.repository import ExpenseRepository
from template.domain.models.split import EqualSplit, PercentageSplit
from template.domain.schema_model import ResponseModel
from template.domain.schemas.expense import (
    ExpenseCreate,
    ExpenseDraftResponse,
    ExpenseResponse,
    SplitStrategySchema,
)
from template.service_layer.auth_service import get_current_member
from template.service_layer.expense_draft_service import build_expense_draft
from template.service_layer.expense_service import ExpenseService, _strategy_to_schema
from template.service_layer.group_service import GroupService
from template.service_layer.member_service import MemberService
from template.service_layer.notification_service import NotificationService
from template.service_layer.push_service import PushService

router = APIRouter(prefix="/groups/{group_id}/expenses", tags=["Expenses"])


# pylint: disable=too-many-arguments, too-many-positional-arguments
@router.post("/parse-image", response_model=ResponseModel[ExpenseDraftResponse])
async def parse_expense_image(
    file: UploadFile = File(...),
    _=Depends(get_current_member),
) -> ResponseModel[ExpenseDraftResponse]:
    """Read an expense off an uploaded screenshot or receipt photo.

    Returns a **draft** for the user to confirm — it never creates the expense. The image is
    parsed by an LLM, which is occasionally wrong, and this is money.
    """
    try:
        draft = build_expense_draft(await file.read(), file.content_type or "")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    return ResponseModel(
        data=ExpenseDraftResponse(
            amount=draft.amount,
            description=draft.description,
            category=draft.category,
            date=draft.date,
            payment_type=PaymentType(draft.payment_type),
            installments=draft.installments,
            currency=draft.currency,
            confidence=draft.confidence,
        )
    )


@router.post("/", status_code=status.HTTP_201_CREATED, response_model=ResponseModel[ExpenseResponse])
def create_expense(
    expense_data: ExpenseCreate,
    background_tasks: BackgroundTasks,
    service: ExpenseService = Depends(get_expense_service),
    member_service: MemberService = Depends(get_member_service),
    group_service: GroupService = Depends(get_group_service),
    repository: ExpenseRepository = Depends(get_repository),
    db: Session = Depends(get_db),
    current_member=Depends(get_current_member),
) -> ResponseModel[ExpenseResponse]:
    """Create a new expense."""
    try:
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
                creator=current_member,
                member_service=member_service,
                group_name=group_name,
                multi_group_member_ids=multi_group_ids,
                group_id=service.group_id,
                push_service=PushService(db),
                push_repo=PushSubscriptionRepository(db),
            )

        # Create response data
        response_data = ExpenseResponse(
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

        return ResponseModel(data=response_data)

    except ValueError as e:
        if "está saldado" in str(e):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.put("/{expense_id}", response_model=ResponseModel[ExpenseResponse])
def update_expense(  # pylint: disable=too-many-locals
    expense_id: int,
    expense_data: ExpenseCreate,
    background_tasks: BackgroundTasks,
    service: ExpenseService = Depends(get_expense_service),
    member_service: MemberService = Depends(get_member_service),
    group_service: GroupService = Depends(get_group_service),
    repository: ExpenseRepository = Depends(get_repository),
    current_member=Depends(get_current_member),
    db: Session = Depends(get_db),
) -> ResponseModel[ExpenseResponse]:
    """Update an existing expense."""
    try:
        # Capture the old state before overwriting
        old_expense = service.get_expense(expense_id)

        updated_expense = service.update_expense(expense_id, expense_data)
        group_service.refresh_archived_state(service.group_id, repository)

        # Schedule notification in background (skip for personal groups)
        if not service.is_personal_group():
            members = service.get_members()
            group_name = service.get_group_name()
            multi_group_ids = service.get_multi_group_member_ids(members)
            background_tasks.add_task(
                NotificationService().notify_expense_updated,
                old=old_expense,
                new=updated_expense,
                actor=current_member,
                members=members,
                member_service=member_service,
                group_name=group_name,
                multi_group_member_ids=multi_group_ids,
                group_id=service.group_id,
                push_service=PushService(db),
                push_repo=PushSubscriptionRepository(db),
            )

        response_data = ExpenseResponse(
            id=updated_expense.id,
            description=updated_expense.description,
            amount=updated_expense.amount,
            date=updated_expense.date,
            category=updated_expense.category.name,
            payer_id=updated_expense.payer_id,
            installments=updated_expense.installments,
            installment_no=updated_expense.installment_no,
            payment_type=updated_expense.payment_type,
            split_strategy=_strategy_to_schema(updated_expense.split_strategy),
            parent_expense_id=updated_expense.parent_expense_id,
            currency=getattr(updated_expense, "currency", "ARS"),
        )

        return ResponseModel(data=response_data)

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.delete("/{expense_id}")
def delete_expense(
    expense_id: int,
    background_tasks: BackgroundTasks,
    service: ExpenseService = Depends(get_expense_service),
    member_service: MemberService = Depends(get_member_service),
    group_service: GroupService = Depends(get_group_service),
    repository: ExpenseRepository = Depends(get_repository),
    current_member=Depends(get_current_member),
    db: Session = Depends(get_db),
) -> None:
    """Delete an expense."""
    try:
        # Capture expense before deleting so we can notify
        expense_to_delete = service.get_expense(expense_id)

        service.delete_expense(expense_id)
        group_service.refresh_archived_state(service.group_id, repository)

        # Skip notification for personal groups
        if expense_to_delete and not service.is_personal_group():
            members = service.get_members()
            group_name = service.get_group_name()
            multi_group_ids = service.get_multi_group_member_ids(members)
            background_tasks.add_task(
                NotificationService().notify_expense_deleted,
                expense=expense_to_delete,
                actor=current_member,
                members=members,
                member_service=member_service,
                group_name=group_name,
                multi_group_member_ids=multi_group_ids,
                group_id=service.group_id,
                push_service=PushService(db),
                push_repo=PushSubscriptionRepository(db),
            )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)) from e


@router.get("/similar", response_model=ResponseModel[list[ExpenseResponse]])
def find_similar_expenses(
    year: int,
    month: int,
    amount: float,
    description: str,
    expense_date: date = Query(..., alias="date"),
    service: ExpenseService = Depends(get_expense_service),
    current_member=Depends(get_current_member),
) -> ResponseModel[list[ExpenseResponse]]:
    """Find expenses in the same month that may be duplicates of a new entry."""
    similar = service.find_similar_expenses(year, month, amount, description, expense_date)
    return ResponseModel(data=similar)


@router.get("/{expense_id}", response_model=ResponseModel[ExpenseResponse])
def get_expense(
    expense_id: int,
    service: ExpenseService = Depends(get_expense_service),
    _=Depends(get_current_member),
) -> ResponseModel[ExpenseResponse]:
    """Get a specific expense by ID."""
    try:
        expense = service.get_expense(expense_id)
        if not expense:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Expense with ID {expense_id} not found",
            )

        if isinstance(expense.split_strategy, EqualSplit):
            split_strategy = SplitStrategySchema(type="equal")
        elif isinstance(expense.split_strategy, PercentageSplit):
            split_strategy = SplitStrategySchema(type="percentage", percentages=expense.split_strategy.percentages)
        else:
            raise ValueError(f"Unknown split strategy type: {type(expense.split_strategy)}")

        response_data = ExpenseResponse(
            id=expense.id,
            description=expense.description,
            amount=expense.amount,
            date=expense.date,
            category=expense.category.name,
            payer_id=expense.payer_id,
            installments=expense.installments,
            installment_no=expense.installment_no,
            payment_type=expense.payment_type,
            split_strategy=split_strategy,
            parent_expense_id=expense.parent_expense_id,
            currency=getattr(expense, "currency", "ARS"),
        )

        return ResponseModel(data=response_data)

    except ValueError as e:
        print(e)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.get("/{expense_id}/parent", response_model=ResponseModel[ExpenseResponse])
def get_parent_expense(
    expense_id: int,
    service: ExpenseService = Depends(get_expense_service),
    _=Depends(get_current_member),
) -> ResponseModel[ExpenseResponse]:
    """Get the parent expense for a given expense ID."""
    try:
        parent_expense = service.get_parent_expense(expense_id)
        if not parent_expense:
            raise HTTPException(
                status_code=404,
                detail="No parent expense found. This expense might be a parent itself or a standalone expense.",
            )

        response_data = ExpenseResponse(
            id=parent_expense.id,
            description=parent_expense.description,
            amount=parent_expense.amount,
            date=parent_expense.date,
            category=parent_expense.category.name,
            payer_id=parent_expense.payer_id,
            installments=parent_expense.installments,
            installment_no=parent_expense.installment_no,
            payment_type=parent_expense.payment_type,
            split_strategy=SplitStrategySchema(
                type="equal" if isinstance(parent_expense.split_strategy, EqualSplit) else "percentage",
                percentages=getattr(parent_expense.split_strategy, "percentages", None),
            ),
            parent_expense_id=parent_expense.parent_expense_id,
            currency=getattr(parent_expense, "currency", "ARS"),
        )

        return ResponseModel(data=response_data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
