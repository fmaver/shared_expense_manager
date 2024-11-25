"""Expense API endpoints."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Path, status

from template.dependencies import get_initialized_manager
from template.domain.models.category import Category
from template.domain.models.models import Expense, ExpenseManager
from template.domain.models.split import EqualSplit, PercentageSplit
from template.domain.schema_model import ResponseModel
from template.domain.schemas.expense import (
    ExpenseCreate,
    ExpenseResponse,
    MonthlyBalanceResponse,
)

router = APIRouter(prefix="/expenses", tags=["Expenses"])


@router.post("/", status_code=status.HTTP_201_CREATED, response_model=ResponseModel[ExpenseResponse])
async def create_expense(
    expense_data: ExpenseCreate, manager: ExpenseManager = Depends(get_initialized_manager)
) -> ResponseModel[ExpenseResponse]:
    """Create a new expense."""
    try:
        if not manager.members:
            raise ValueError("Cannot create expense: No members exist in the system")

        print(f"Creating expense: {expense_data.description} for amount {expense_data.amount}")

        split_type: str = expense_data.split_strategy.type
        # Create split strategy based on the type
        if split_type == "equal":
            split_strategy = EqualSplit()
        else:  # percentage
            split_strategy = PercentageSplit(expense_data.split_strategy.percentages)

        # Create Category instance
        category = Category()
        category.name = expense_data.category.name

        # Create the Expense object
        expense = Expense(
            description=expense_data.description,
            amount=expense_data.amount,
            date=expense_data.date,
            category=category,
            payer_id=expense_data.payer_id,
            payment_type=expense_data.payment_type,
            installments=expense_data.installments,
            split_strategy=split_strategy,
        )

        # Add the expense
        manager.create_and_add_expense(expense)

        # Create response data
        response_data = ExpenseResponse(
            description=expense.description,
            amount=expense.amount,
            date=expense.date,
            category=expense.category.name,
            payer_id=expense.payer_id,
            installments=expense.installments,
            installment_no=1,
            payment_type=expense_data.payment_type,
        )

        return ResponseModel(data=response_data)

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.get("/{year}/{month}", response_model=ResponseModel[MonthlyBalanceResponse], response_model_exclude_none=True)
async def get_monthly_balance(
    year: int = Path(..., ge=1900, le=9999),
    month: int = Path(..., ge=1, le=12),
    manager: ExpenseManager = Depends(get_initialized_manager),
):
    """
    Get the monthly balance for a specific month.

    Args:
        year: The year (1900-9999)
        month: The month (1-12)

    Returns:
        Monthly balance including expenses and member balances

    Raises:
        HTTPException: If the date is invalid or no expenses are found
    """
    try:
        # Validate date
        datetime(year, month, 1)

        # Get balance from expense manager
        balance = manager.get_monthly_balance(year, month)
        if not balance:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No expenses found for {year}-{month:02d}",
            )

        # Convert Expense objects to ExpenseResponse objects
        expense_responses = [
            ExpenseResponse(
                description=expense.description,
                amount=expense.amount,
                date=expense.date,
                category=expense.category.name,
                payer_id=expense.payer_id,
                installments=expense.installments,
                installment_no=expense.installment_no,
                payment_type=expense.payment_type,
            )
            for expense in balance.expenses
        ]

        return ResponseModel(
            data=MonthlyBalanceResponse(
                year=year,
                month=month,
                expenses=expense_responses,  # Now using the converted responses
                balances=balance.balances,
                is_settled=balance.is_settled,
            )
        )

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
