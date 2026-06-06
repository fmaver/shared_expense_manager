"""Monthly Share API endpoints."""

import io
from datetime import datetime
from typing import Callable

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Path, status
from fastapi.responses import StreamingResponse

from template.dependencies import (
    get_expense_service,
    get_member_service,
    get_recurring_group_expense_materializer,
)
from template.domain.models.pdf_builder import build_monthly_report
from template.domain.schema_model import ResponseModel
from template.domain.schemas.expense import MonthlyBalanceResponse
from template.service_layer.auth_service import get_current_member
from template.service_layer.expense_service import ExpenseService
from template.service_layer.member_service import MemberService
from template.service_layer.notification_service import NotificationService

router = APIRouter(prefix="/groups/{group_id}/shares", tags=["MonthlyShares"])


@router.get("/{year}/{month}", response_model=ResponseModel[MonthlyBalanceResponse])
async def get_monthly_balance(
    year: int = Path(..., ge=1900, le=9999),
    month: int = Path(..., ge=1, le=12),
    service: ExpenseService = Depends(get_expense_service),
    materialize: Callable[[int, int], None] = Depends(get_recurring_group_expense_materializer),
) -> ResponseModel[MonthlyBalanceResponse]:
    """Get the monthly balance for a specific month."""
    try:
        # Validate date
        datetime(year, month, 1)

        # Lazily materialize any recurring group expenses for this period.
        materialize(year, month)

        # Get expenses from service
        expenses = service.get_monthly_expenses(year, month)
        if not expenses:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No expenses found for {year}-{month:02d}",
            )

        monthly_share = service.get_monthly_balance(year, month)
        # Print monthly share details
        print(f"\nMonthly share for {year}-{month:02d}:")
        print(f"Number of expenses: {len(monthly_share.expenses)}")
        print(f"Is settled: {monthly_share.is_settled}")
        print("\nBalances:")
        for member_id, balance in monthly_share.balances.items():
            print(f"Member {member_id}: {balance}")

        return ResponseModel(
            data=MonthlyBalanceResponse(
                year=year,
                month=month,
                expenses=expenses,
                balances=monthly_share.balances,
                is_settled=monthly_share.is_settled,
            )
        )

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post("/settle/{year}/{month}", response_model=ResponseModel[MonthlyBalanceResponse])
async def settle_monthly_share(  # pylint: disable=too-many-positional-arguments,too-many-arguments
    background_tasks: BackgroundTasks,
    year: int = Path(..., ge=1900, le=9999),
    month: int = Path(..., ge=1, le=12),
    service: ExpenseService = Depends(get_expense_service),
    member_service: MemberService = Depends(get_member_service),
    current_member=Depends(get_current_member),
) -> ResponseModel[MonthlyBalanceResponse]:
    """Settle the monthly share for a specific month."""
    try:
        monthly_share = service.settle_monthly_share(year, month)
        print("Monthly Share Settled")
        if not monthly_share:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No monthly share found for {year}-{month:02d}",
            )

        monthly_share = service.get_monthly_balance(year, month)

        expenses = service.get_monthly_expenses(year, month)
        if not expenses:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No expenses found for {year}-{month:02d}",
            )

        if not service.is_personal_group():
            members = service.get_members()
            group_name = service.get_group_name() or ""
            background_tasks.add_task(
                NotificationService().notify_settlement,
                year=year,
                month=month,
                actor_member_id=current_member.id,
                members=members,
                member_service=member_service,
                group_name=group_name,
                group_id=service.group_id,
            )

        return ResponseModel(
            data=MonthlyBalanceResponse(
                year=year,
                month=month,
                expenses=expenses,
                balances=monthly_share.balances,
                is_settled=monthly_share.is_settled,
            )
        )

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post("/unsettle/{year}/{month}", response_model=ResponseModel[MonthlyBalanceResponse])
async def unsettle_monthly_share(
    year: int = Path(..., ge=1900, le=9999),
    month: int = Path(..., ge=1, le=12),
    service: ExpenseService = Depends(get_expense_service),
) -> ResponseModel[MonthlyBalanceResponse]:
    """Reverse the settlement of a month: removes auto-generated balancing expenses and reopens it."""
    try:
        service.unsettle_monthly_share(year, month)

        monthly_share = service.get_monthly_balance(year, month)
        expenses = service.get_monthly_expenses(year, month)

        return ResponseModel(
            data=MonthlyBalanceResponse(
                year=year,
                month=month,
                expenses=expenses or [],
                balances=monthly_share.balances if monthly_share else {},
                is_settled=False,
            )
        )

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post("/recalculate/{year}/{month}", response_model=ResponseModel[MonthlyBalanceResponse])
async def recalculate_monthly_share(
    year: int = Path(..., ge=1900, le=9999),
    month: int = Path(..., ge=1, le=12),
    service: ExpenseService = Depends(get_expense_service),
) -> ResponseModel[MonthlyBalanceResponse]:
    """Recalculate the monthly share for a specific month."""
    try:
        monthly_share = service.recalculate_monthly_share(year, month)
        print("Monthly Share Recalculated")
        if not monthly_share:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No monthly share found for {year}-{month:02d}",
            )
        print(f"Balances recalculatedfor {year}-{month:02d}: {monthly_share.balances}")
        monthly_share = service.get_monthly_balance(year, month)
        print(f"GettingBalances for {year}-{month:02d}: {monthly_share.balances}")

        expenses = service.get_monthly_expenses(year, month)
        if not expenses:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No expenses found for {year}-{month:02d}",
            )

        return ResponseModel(
            data=MonthlyBalanceResponse(
                year=year,
                month=month,
                expenses=expenses,
                balances=monthly_share.balances,
                is_settled=monthly_share.is_settled,
            )
        )

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.get("/{year}/{month}/pdf")
async def download_monthly_pdf(
    year: int = Path(..., ge=1900, le=9999),
    month: int = Path(..., ge=1, le=12),
    service: ExpenseService = Depends(get_expense_service),
    current_member=Depends(get_current_member),
) -> StreamingResponse:
    """Download the monthly balance as a designed PDF report."""
    try:
        datetime(year, month, 1)

        expenses = service.get_monthly_expenses(year, month)
        if not expenses:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No expenses found for {year}-{month:02d}",
            )

        monthly_share = service.get_monthly_balance(year, month)
        member_names = service.get_member_names()

        pdf_bytes = build_monthly_report(
            expenses=expenses,
            balances=monthly_share.balances if monthly_share else {},
            member_names=member_names,
            year=year,
            month=month,
            is_settled=monthly_share.is_settled if monthly_share else False,
        )

        filename = f"balance_{year}_{month:02d}.pdf"
        return StreamingResponse(
            io.BytesIO(pdf_bytes),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
