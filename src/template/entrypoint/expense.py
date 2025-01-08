"""Expense API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status

from template.dependencies import get_expense_service
from template.domain.models.split import EqualSplit, PercentageSplit
from template.domain.schema_model import ResponseModel
from template.domain.schemas.expense import (
    ExpenseCreate,
    ExpenseResponse,
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


@router.put("/{expense_id}", response_model=ResponseModel[ExpenseResponse])
async def update_expense(
    expense_id: int, expense_data: ExpenseCreate, service: ExpenseService = Depends(get_expense_service)
) -> ResponseModel[ExpenseResponse]:
    """Update an existing expense."""
    try:
        updated_expense = service.update_expense(expense_id, expense_data)

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
            split_strategy=SplitStrategySchema(
                type="equal" if isinstance(updated_expense.split_strategy, EqualSplit) else "percentage",
                percentages=getattr(updated_expense.split_strategy, "percentages", None),
            ),
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
