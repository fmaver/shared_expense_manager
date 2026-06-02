"""Personal API endpoints — personal group, income, and ledger."""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from template.adapters.database import get_db
from template.adapters.repositories import GroupRepository
from template.dependencies import (
    get_group_service,
    get_income_repository,
    get_personal_ledger_service,
)
from template.domain.schema_model import ResponseModel
from template.domain.schemas.group import GroupMemberResponse, GroupResponse
from template.domain.schemas.income import (
    IncomeInstanceResponse,
    PersonalLedgerResponse,
    RecurringIncomeCreate,
    RecurringIncomeResponse,
    RecurringIncomeUpdate,
    VariableIncomeCreate,
    VariableIncomeUpdate,
)
from template.service_layer.auth_service import get_current_member
from template.service_layer.group_service import GroupService

router = APIRouter(prefix="/personal", tags=["Personal"])


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _group_to_response(group, members) -> GroupResponse:
    """Convert domain Group + members list to GroupResponse schema."""
    return GroupResponse(
        id=group.id,
        name=group.name,
        status=group.status,
        group_type=group.group_type,
        created_at=group.created_at,
        members=[
            GroupMemberResponse(member_id=m.id, name=m.name, email=m.email, telephone=m.telephone, is_stub=m.is_stub)
            for m in members
        ],
    )


def _recurring_to_response(template) -> RecurringIncomeResponse:
    return RecurringIncomeResponse(
        id=template.id,
        owner_member_id=template.owner_member_id,
        personal_group_id=template.personal_group_id,
        label=template.label,
        amount=template.amount,
        active=template.active,
        created_at=template.created_at,
        updated_at=template.updated_at,
    )


def _instance_to_response(instance) -> IncomeInstanceResponse:
    return IncomeInstanceResponse(
        id=instance.id,
        personal_group_id=instance.personal_group_id,
        owner_member_id=instance.owner_member_id,
        year=instance.year,
        month=instance.month,
        source=instance.source,
        recurring_income_id=instance.recurring_income_id,
        label=instance.label,
        amount=instance.amount,
    )


# ---------------------------------------------------------------------------
# Group endpoint
# ---------------------------------------------------------------------------


@router.get("/group", response_model=ResponseModel[GroupResponse])
async def get_personal_group(
    current_member=Depends(get_current_member),
    group_service: GroupService = Depends(get_group_service),
    db: Session = Depends(get_db),
) -> ResponseModel[GroupResponse]:
    """Get or create the current member's personal group."""
    personal_group = group_service.get_or_create_personal_group(current_member.id)
    members = GroupRepository(db).list_members(personal_group.id)
    return ResponseModel(data=_group_to_response(personal_group, members))


# ---------------------------------------------------------------------------
# Ledger endpoint
# ---------------------------------------------------------------------------


@router.get("/ledger/{year}/{month}", response_model=ResponseModel[PersonalLedgerResponse])
async def get_personal_ledger(
    year: int,
    month: int,
    current_member=Depends(get_current_member),
    ledger_service=Depends(get_personal_ledger_service),
) -> ResponseModel[PersonalLedgerResponse]:
    """Get the personal financial ledger for the given month."""
    ledger = ledger_service.get_ledger(current_member.id, year, month)
    return ResponseModel(data=ledger)


# ---------------------------------------------------------------------------
# Recurring income endpoints
# ---------------------------------------------------------------------------


@router.get("/income/recurring", response_model=ResponseModel[list[RecurringIncomeResponse]])
async def list_recurring_incomes(
    current_member=Depends(get_current_member),
    group_service: GroupService = Depends(get_group_service),
    income_repo=Depends(get_income_repository),
) -> ResponseModel[list[RecurringIncomeResponse]]:
    """List all recurring income templates for the current member's personal group."""
    personal_group = group_service.get_or_create_personal_group(current_member.id)
    templates = income_repo.list_recurring(personal_group.id)
    return ResponseModel(data=[_recurring_to_response(t) for t in templates])


@router.post("/income/recurring", status_code=201, response_model=ResponseModel[RecurringIncomeResponse])
async def create_recurring_income(
    data: RecurringIncomeCreate,
    current_member=Depends(get_current_member),
    group_service: GroupService = Depends(get_group_service),
    income_repo=Depends(get_income_repository),
) -> ResponseModel[RecurringIncomeResponse]:
    """Create a new recurring income template and immediately materialize it for the current month."""
    personal_group = group_service.get_or_create_personal_group(current_member.id)
    template = income_repo.create_recurring(
        owner_member_id=current_member.id,
        personal_group_id=personal_group.id,
        label=data.label,
        amount=data.amount,
    )
    # Immediately snapshot for the current month
    today = date.today()
    income_repo.upsert_recurring_instance(
        personal_group_id=personal_group.id,
        owner_member_id=current_member.id,
        year=today.year,
        month=today.month,
        recurring_income_id=template.id,
        label=template.label,
        amount=template.amount,
    )
    return ResponseModel(data=_recurring_to_response(template))


@router.patch("/income/recurring/{income_id}", response_model=ResponseModel[RecurringIncomeResponse])
async def update_recurring_income(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    income_id: int,
    data: RecurringIncomeUpdate,
    viewed_year: Optional[int] = None,
    viewed_month: Optional[int] = None,
    current_member=Depends(get_current_member),
    group_service: GroupService = Depends(get_group_service),
    income_repo=Depends(get_income_repository),
) -> ResponseModel[RecurringIncomeResponse]:
    """Update a recurring income template.

    Re-syncs the current calendar month's snapshot. If the caller passes
    viewed_year/viewed_month (the month the user is currently looking at),
    that month's snapshot is also updated so the change is immediately visible.
    """
    personal_group = group_service.get_or_create_personal_group(current_member.id)
    template = income_repo.get_recurring(income_id)
    if not template or template.personal_group_id != personal_group.id:
        raise HTTPException(status_code=404, detail="Recurring income not found")
    updated = income_repo.update_recurring(income_id, label=data.label, amount=data.amount, active=data.active)
    today = date.today()
    months_to_sync = {(today.year, today.month)}
    if viewed_year and viewed_month:
        months_to_sync.add((viewed_year, viewed_month))
    for yr, mo in months_to_sync:
        income_repo.update_recurring_instance_for_month(
            personal_group_id=personal_group.id,
            recurring_income_id=income_id,
            year=yr,
            month=mo,
            new_label=updated.label,
            new_amount=updated.amount,
        )
    return ResponseModel(data=_recurring_to_response(updated))


@router.delete("/income/recurring/{income_id}", response_model=ResponseModel[RecurringIncomeResponse])
async def delete_recurring_income(
    income_id: int,
    current_member=Depends(get_current_member),
    group_service: GroupService = Depends(get_group_service),
    income_repo=Depends(get_income_repository),
) -> ResponseModel[RecurringIncomeResponse]:
    """Deactivate a recurring income template (or delete it if no instances reference it)."""
    personal_group = group_service.get_or_create_personal_group(current_member.id)
    template = income_repo.get_recurring(income_id)
    if not template or template.personal_group_id != personal_group.id:
        raise HTTPException(status_code=404, detail="Recurring income not found")
    if income_repo.has_instances(income_id):
        # Has historical snapshots — deactivate to preserve history, but remove
        # the current month's snapshot so it disappears from the ledger immediately
        updated = income_repo.update_recurring(income_id, active=False)
        today = date.today()
        income_repo.delete_recurring_instance_for_month(
            personal_group_id=personal_group.id,
            recurring_income_id=income_id,
            year=today.year,
            month=today.month,
        )
        return ResponseModel(data=_recurring_to_response(updated))
    income_repo.delete_recurring(income_id)
    return ResponseModel(data=_recurring_to_response(template))


# ---------------------------------------------------------------------------
# Variable income endpoints
# ---------------------------------------------------------------------------


@router.get("/income/variable/{year}/{month}", response_model=ResponseModel[list[IncomeInstanceResponse]])
async def list_variable_incomes(
    year: int,
    month: int,
    current_member=Depends(get_current_member),
    group_service: GroupService = Depends(get_group_service),
    income_repo=Depends(get_income_repository),
) -> ResponseModel[list[IncomeInstanceResponse]]:
    """List variable (one-off) income entries for the given month."""
    personal_group = group_service.get_or_create_personal_group(current_member.id)
    instances = income_repo.list_instances_for_month(personal_group.id, year, month)
    variable = [i for i in instances if i.source == "variable"]
    return ResponseModel(data=[_instance_to_response(i) for i in variable])


@router.post("/income/variable", status_code=201, response_model=ResponseModel[IncomeInstanceResponse])
async def create_variable_income(
    data: VariableIncomeCreate,
    current_member=Depends(get_current_member),
    group_service: GroupService = Depends(get_group_service),
    income_repo=Depends(get_income_repository),
) -> ResponseModel[IncomeInstanceResponse]:
    """Create a one-off variable income entry."""
    personal_group = group_service.get_or_create_personal_group(current_member.id)
    instance = income_repo.create_variable_instance(
        personal_group_id=personal_group.id,
        owner_member_id=current_member.id,
        year=data.year,
        month=data.month,
        label=data.label,
        amount=data.amount,
    )
    return ResponseModel(data=_instance_to_response(instance))


@router.patch("/income/variable/{instance_id}", response_model=ResponseModel[IncomeInstanceResponse])
async def update_variable_income(
    instance_id: int,
    data: VariableIncomeUpdate,
    current_member=Depends(get_current_member),
    group_service: GroupService = Depends(get_group_service),
    income_repo=Depends(get_income_repository),
) -> ResponseModel[IncomeInstanceResponse]:
    """Update a variable income entry."""
    personal_group = group_service.get_or_create_personal_group(current_member.id)
    instance = income_repo.get_instance(instance_id)
    if not instance or instance.personal_group_id != personal_group.id:
        raise HTTPException(status_code=404, detail="Income entry not found")
    updated = income_repo.update_instance(instance_id, label=data.label, amount=data.amount)
    return ResponseModel(data=_instance_to_response(updated))


@router.delete("/income/variable/{instance_id}", status_code=204)
async def delete_variable_income(
    instance_id: int,
    current_member=Depends(get_current_member),
    group_service: GroupService = Depends(get_group_service),
    income_repo=Depends(get_income_repository),
):
    """Delete a variable income entry."""
    personal_group = group_service.get_or_create_personal_group(current_member.id)
    instance = income_repo.get_instance(instance_id)
    if not instance or instance.personal_group_id != personal_group.id:
        raise HTTPException(status_code=404, detail="Income entry not found")
    income_repo.delete_instance(instance_id)
