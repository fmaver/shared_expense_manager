"""Endpoints de vencimientos recurrentes de un grupo."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status

from template.adapters.repositories import DueDateRepository, GroupRepository
from template.dependencies import get_due_date_repository, get_group_repository
from template.domain.schema_model import ResponseModel
from template.domain.schemas.due_date import DueDateCreate, DueDateResponse, DueDateUpdate
from template.service_layer.auth_service import get_current_member

router = APIRouter(prefix="/groups/{group_id}/due-dates", tags=["DueDates"])


def _assert_group_membership(group_id: int, current_member, group_repo: GroupRepository) -> None:
    """Raise HTTP 403 if current_member does not belong to group_id."""
    if not group_repo.is_member(group_id, current_member.id):
        raise HTTPException(status_code=403, detail="Not a member of this group")


def _assert_belongs_to_group(due_date_id: int, group_id: int, repo: DueDateRepository) -> None:
    """404 si el vencimiento no existe o es de otro grupo.

    Se comprueba la pertenencia al grupo, no solo la existencia: sin esto, un miembro de
    cualquier grupo podría editar el vencimiento de otro pasando su propio group_id.
    """
    model = repo.get(due_date_id)
    if model is None or model.group_id != group_id:
        raise HTTPException(status_code=404, detail="Due date not found")


@router.get("/", response_model=ResponseModel[List[DueDateResponse]])
def list_due_dates(
    group_id: int,
    repo: DueDateRepository = Depends(get_due_date_repository),
    group_repo: GroupRepository = Depends(get_group_repository),
    current_member=Depends(get_current_member),
) -> ResponseModel[List[DueDateResponse]]:
    """Listar los vencimientos del grupo."""
    _assert_group_membership(group_id, current_member, group_repo)
    return ResponseModel(data=repo.list_for_group(group_id))


@router.post("/", status_code=status.HTTP_201_CREATED, response_model=ResponseModel[DueDateResponse])
def create_due_date(
    group_id: int,
    data: DueDateCreate,
    repo: DueDateRepository = Depends(get_due_date_repository),
    group_repo: GroupRepository = Depends(get_group_repository),
    current_member=Depends(get_current_member),
) -> ResponseModel[DueDateResponse]:
    """Crear un vencimiento en el grupo."""
    _assert_group_membership(group_id, current_member, group_repo)
    return ResponseModel(data=repo.create(group_id, current_member.id, data))


@router.put("/{due_date_id}", response_model=ResponseModel[DueDateResponse])
def update_due_date(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    group_id: int,
    due_date_id: int,
    data: DueDateUpdate,
    repo: DueDateRepository = Depends(get_due_date_repository),
    group_repo: GroupRepository = Depends(get_group_repository),
    current_member=Depends(get_current_member),
) -> ResponseModel[DueDateResponse]:
    """Editar un vencimiento. Update parcial: solo se escribe lo enviado."""
    _assert_group_membership(group_id, current_member, group_repo)
    _assert_belongs_to_group(due_date_id, group_id, repo)
    return ResponseModel(data=repo.update(due_date_id, data))


@router.delete("/{due_date_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_due_date(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    group_id: int,
    due_date_id: int,
    repo: DueDateRepository = Depends(get_due_date_repository),
    group_repo: GroupRepository = Depends(get_group_repository),
    current_member=Depends(get_current_member),
) -> None:
    """Borrar un vencimiento y sus avisos ya enviados."""
    _assert_group_membership(group_id, current_member, group_repo)
    _assert_belongs_to_group(due_date_id, group_id, repo)
    repo.delete(due_date_id)
