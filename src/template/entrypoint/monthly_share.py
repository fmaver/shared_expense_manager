"""Monthly Share API endpoints."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Path, status

from template.dependencies import get_expense_service
from template.domain.schema_model import ResponseModel
from template.domain.schemas.expense import MonthlyBalanceResponse
from template.service_layer.expense_service import ExpenseService

router = APIRouter(prefix="/shares", tags=["MonthlyShares"])


@router.get("/{year}/{month}", response_model=ResponseModel[MonthlyBalanceResponse])
async def get_monthly_balance(
    year: int = Path(..., ge=1900, le=9999),
    month: int = Path(..., ge=1, le=12),
    service: ExpenseService = Depends(get_expense_service),
) -> ResponseModel[MonthlyBalanceResponse]:
    """Get the monthly balance for a specific month."""
    try:
        # Validate date
        datetime(year, month, 1)

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
async def settle_monthly_share(
    year: int = Path(..., ge=1900, le=9999),
    month: int = Path(..., ge=1, le=12),
    service: ExpenseService = Depends(get_expense_service),
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

        monthly_share = service.get_monthly_balance(year, month)

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
