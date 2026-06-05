"""Recurring group expense API endpoints."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query

from template.adapters.repositories import (
    GroupRepository,
    RecurringGroupExpenseRepository,
)
from template.dependencies import (
    get_group_repository,
    get_recurring_group_expense_repository,
)
from template.domain.schema_model import ResponseModel
from template.domain.schemas.expense import (
    RecurringGroupExpenseCreate,
    RecurringGroupExpenseResponse,
    RecurringGroupExpenseUpdate,
)
from template.service_layer.auth_service import get_current_member

router = APIRouter(prefix="/groups/{group_id}/expenses/recurring", tags=["RecurringExpenses"])


def _assert_group_membership(group_id: int, current_member, group_repo: GroupRepository) -> None:
    """Raise HTTP 403 if current_member does not belong to group_id."""
    if not group_repo.is_member(group_id, current_member.id):
        raise HTTPException(status_code=403, detail="Not a member of this group")


@router.post("/", status_code=201, response_model=ResponseModel[RecurringGroupExpenseResponse])
async def create_recurring_expense(
    group_id: int,
    data: RecurringGroupExpenseCreate,
    repo: RecurringGroupExpenseRepository = Depends(get_recurring_group_expense_repository),
    group_repo: GroupRepository = Depends(get_group_repository),
    current_member=Depends(get_current_member),
) -> ResponseModel[RecurringGroupExpenseResponse]:
    """Create a new recurring group expense template and immediately materialize it for the start month.

    Notification is not sent at template creation time — notifications fire when the recurring
    expense materializes as a real Expense row during the monthly share view.
    """
    _assert_group_membership(group_id, current_member, group_repo)
    template = repo.create(group_id, data)
    repo.upsert_instance(template.id, group_id, data.start_year, data.start_month)
    return ResponseModel(data=template)


@router.get("/", response_model=ResponseModel[List[RecurringGroupExpenseResponse]])
async def list_recurring_expenses(
    group_id: int,
    repo: RecurringGroupExpenseRepository = Depends(get_recurring_group_expense_repository),
    group_repo: GroupRepository = Depends(get_group_repository),
    current_member=Depends(get_current_member),
) -> ResponseModel[List[RecurringGroupExpenseResponse]]:
    """List active recurring expense templates for a group."""
    _assert_group_membership(group_id, current_member, group_repo)
    templates = repo.list_for_group(group_id, active_only=True)
    return ResponseModel(data=templates)


@router.patch("/{template_id}", response_model=ResponseModel[RecurringGroupExpenseResponse])
async def update_recurring_expense(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    group_id: int,
    template_id: int,
    data: RecurringGroupExpenseUpdate,
    viewed_year: int = Query(..., ge=2000, le=2100),
    viewed_month: int = Query(..., ge=1, le=12),
    repo: RecurringGroupExpenseRepository = Depends(get_recurring_group_expense_repository),
    group_repo: GroupRepository = Depends(get_group_repository),
    current_member=Depends(get_current_member),
) -> ResponseModel[RecurringGroupExpenseResponse]:
    """Update a recurring group expense template.

    Deletes instances from viewed_month onwards so they re-materialize with the updated values.
    """
    _assert_group_membership(group_id, current_member, group_repo)
    template = repo.get(template_id)
    if not template or template.group_id != group_id:
        raise HTTPException(status_code=404, detail="Recurring expense not found")
    if not template.active:
        raise HTTPException(status_code=404, detail="Recurring expense not found")
    updated = repo.update(template_id, data)
    if updated is None:
        raise HTTPException(status_code=404, detail="Recurring expense not found")
    repo.delete_instances_from_month_onwards(template_id, viewed_year, viewed_month)
    return ResponseModel(data=updated)


@router.delete("/{template_id}", status_code=204)
async def delete_recurring_expense(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    group_id: int,
    template_id: int,
    viewed_year: int = Query(..., ge=2000, le=2100),
    viewed_month: int = Query(..., ge=1, le=12),
    repo: RecurringGroupExpenseRepository = Depends(get_recurring_group_expense_repository),
    group_repo: GroupRepository = Depends(get_group_repository),
    current_member=Depends(get_current_member),
) -> None:
    """Deactivate or hard-delete a recurring group expense template.

    If the template has any existing instances (meaning it has already been materialized),
    it is deactivated (soft-delete) and instances from viewed_month onwards are removed.
    If no instances exist the template is hard-deleted entirely.
    """
    _assert_group_membership(group_id, current_member, group_repo)
    template = repo.get(template_id)
    if not template or template.group_id != group_id:
        raise HTTPException(status_code=404, detail="Recurring expense not found")
    if repo.has_instances(template_id):
        repo.deactivate(template_id)
        repo.delete_instances_from_month_onwards(template_id, viewed_year, viewed_month)
    else:
        repo.hard_delete(template_id)
