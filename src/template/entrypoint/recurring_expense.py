"""Recurring group expense API endpoints."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query

from template.dependencies import get_recurring_group_expense_repository
from template.adapters.repositories import RecurringGroupExpenseRepository
from template.domain.schema_model import ResponseModel
from template.domain.schemas.expense import (
    RecurringGroupExpenseCreate,
    RecurringGroupExpenseResponse,
    RecurringGroupExpenseUpdate,
)

router = APIRouter(prefix="/groups/{group_id}/expenses/recurring", tags=["recurring-expenses"])


@router.post("/", status_code=201, response_model=ResponseModel[RecurringGroupExpenseResponse])
async def create_recurring_expense(
    group_id: int,
    data: RecurringGroupExpenseCreate,
    repo: RecurringGroupExpenseRepository = Depends(get_recurring_group_expense_repository),
) -> ResponseModel[RecurringGroupExpenseResponse]:
    """Create a new recurring group expense template and immediately materialize it for the start month.

    Notification is not sent at template creation time — notifications fire when the recurring
    expense materializes as a real Expense row during the monthly share view.
    """
    template = repo.create(group_id, data)
    repo.upsert_instance(template.id, group_id, data.start_year, data.start_month)
    return ResponseModel(data=template)


@router.get("/", response_model=ResponseModel[List[RecurringGroupExpenseResponse]])
async def list_recurring_expenses(
    group_id: int,
    repo: RecurringGroupExpenseRepository = Depends(get_recurring_group_expense_repository),
) -> ResponseModel[List[RecurringGroupExpenseResponse]]:
    """List active recurring expense templates for a group."""
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
) -> ResponseModel[RecurringGroupExpenseResponse]:
    """Update a recurring group expense template.

    Deletes instances from viewed_month onwards so they re-materialize with the updated values.
    """
    template = repo.get(template_id)
    if not template or template.group_id != group_id:
        raise HTTPException(status_code=404, detail="Recurring expense not found")
    updated = repo.update(template_id, data)
    if updated is None:
        raise HTTPException(status_code=404, detail="Recurring expense not found")
    repo.delete_instances_from_month_onwards(template_id, viewed_year, viewed_month)
    return ResponseModel(data=updated)


@router.delete("/{template_id}", response_model=ResponseModel[None])
async def delete_recurring_expense(
    group_id: int,
    template_id: int,
    viewed_year: int = Query(..., ge=2000, le=2100),
    viewed_month: int = Query(..., ge=1, le=12),
    repo: RecurringGroupExpenseRepository = Depends(get_recurring_group_expense_repository),
) -> ResponseModel[None]:
    """Deactivate or hard-delete a recurring group expense template.

    If the template has any existing instances (meaning it has already been materialized),
    it is deactivated (soft-delete) and instances from viewed_month onwards are removed.
    If no instances exist the template is hard-deleted entirely.
    """
    template = repo.get(template_id)
    if not template or template.group_id != group_id:
        raise HTTPException(status_code=404, detail="Recurring expense not found")
    if repo.has_instances(template_id):
        repo.deactivate(template_id)
        repo.delete_instances_from_month_onwards(template_id, viewed_year, viewed_month)
    else:
        repo.hard_delete(template_id)
    return ResponseModel(data=None)
