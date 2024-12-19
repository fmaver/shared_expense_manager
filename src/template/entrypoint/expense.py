"""Expense API endpoints."""
import os
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Path, status

from template.dependencies import get_expense_service
from template.domain.models.split import EqualSplit, PercentageSplit
from template.domain.schema_model import ResponseModel
from template.domain.schemas.expense import (
    ExpenseCreate,
    ExpenseResponse,
    MonthlyBalanceResponse,
    SplitStrategySchema,
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
        token = os.getenv("TOKEN")
        print("\nToken:")
        print(f"Token: {token}")

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


@router.put("/{expense_id}", response_model=ResponseModel[ExpenseResponse])
async def update_expense(
    expense_id: int, expense_data: ExpenseCreate, service: ExpenseService = Depends(get_expense_service)
) -> ResponseModel[ExpenseResponse]:
    """Update an existing expense."""
    try:
        updated_expense = service.update_expense(expense_id, expense_data)

        response_data = ExpenseResponse(
            description=updated_expense.description,
            amount=updated_expense.amount,
            date=updated_expense.date,
            category=updated_expense.category.name,
            payer_id=updated_expense.payer_id,
            installments=updated_expense.installments,
            installment_no=updated_expense.installment_no,
            payment_type=updated_expense.payment_type,
            split_strategy=updated_expense.split_strategy,
        )

        return ResponseModel(data=response_data)

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.delete("/{expense_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_expense(expense_id: int, service: ExpenseService = Depends(get_expense_service)) -> None:
    """Delete an existing expense."""
    try:
        service.delete_expense(expense_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.get("/{expense_id}", response_model=ResponseModel[ExpenseResponse])
async def get_expense(
    expense_id: int, service: ExpenseService = Depends(get_expense_service)
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
            description=expense.description,
            amount=expense.amount,
            date=expense.date,
            category=expense.category.name,
            payer_id=expense.payer_id,
            installments=expense.installments,
            installment_no=expense.installment_no,
            payment_type=expense.payment_type,
            split_strategy=split_strategy,
        )

        return ResponseModel(data=response_data)

    except ValueError as e:
        print(e)
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
