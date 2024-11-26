"""Expense API endpoints."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Path, status

from template.dependencies import get_expense_service
from template.domain.schema_model import ResponseModel
from template.domain.schemas.expense import (
    ExpenseCreate,
    ExpenseResponse,
    MonthlyBalanceResponse,
)
from template.service_layer.expense_service import ExpenseService

router = APIRouter(prefix="/expenses", tags=["Expenses"])


@router.post("/", status_code=status.HTTP_201_CREATED, response_model=ResponseModel[ExpenseResponse])
async def create_expense(
    expense_data: ExpenseCreate, service: ExpenseService = Depends(get_expense_service)
) -> ResponseModel[ExpenseResponse]:
    """Create a new expense."""
    try:
        service.create_expense(expense_data)

        # Create response data
        response_data = ExpenseResponse(
            description=expense_data.description,
            amount=expense_data.amount,
            date=expense_data.date,
            category=expense_data.category.name,
            payer_id=expense_data.payer_id,
            installments=expense_data.installments,
            installment_no=1,
            payment_type=expense_data.payment_type,
            split_strategy=expense_data.split_strategy,
        )

        return ResponseModel(data=response_data)

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


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
