"""Endpoints for the iOS shortcut ("carga rápida"). Auth: the personal shortcut token only."""

from fastapi import APIRouter, BackgroundTasks, Depends, File, UploadFile

from template.dependencies import get_quick_capture_service
from template.domain.models.member import Member
from template.domain.schema_model import ResponseModel
from template.domain.schemas.quick_capture import (
    QuickCaptureConfirm,
    QuickCaptureMessage,
    QuickCaptureResult,
)
from template.service_layer.quick_capture_service import QuickCaptureService
from template.service_layer.shortcut_token_service import get_shortcut_member

router = APIRouter(prefix="/quick-capture", tags=["QuickCapture"])


@router.post("", response_model=ResponseModel[QuickCaptureResult])
def capture(
    file: UploadFile = File(...),
    member: Member = Depends(get_shortcut_member),
    service: QuickCaptureService = Depends(get_quick_capture_service),
) -> ResponseModel[QuickCaptureResult]:
    """Store and read a screenshot. Answers the summary and menu; never creates the expense."""
    return ResponseModel(data=service.capture(member, file.file.read(), file.content_type or ""))


@router.post("/{draft_id}/confirm", response_model=ResponseModel[QuickCaptureMessage])
def confirm(
    draft_id: int,
    body: QuickCaptureConfirm,
    background_tasks: BackgroundTasks,
    member: Member = Depends(get_shortcut_member),
    service: QuickCaptureService = Depends(get_quick_capture_service),
) -> ResponseModel[QuickCaptureMessage]:
    """Create the expense from the draft in the chosen group."""
    expense = service.confirm(member, draft_id, body.group_id, background_tasks)
    return ResponseModel(data=QuickCaptureMessage(message=service.confirmed_message(expense, body.group_id)))


@router.post("/{draft_id}/keep", response_model=ResponseModel[QuickCaptureMessage])
def keep(
    draft_id: int,
    member: Member = Depends(get_shortcut_member),
    service: QuickCaptureService = Depends(get_quick_capture_service),
) -> ResponseModel[QuickCaptureMessage]:
    """Leave the draft for review in the app (and push the pending list)."""
    service.keep(member, draft_id)
    return ResponseModel(data=QuickCaptureMessage(message="Guardado en borradores"))


@router.delete("/{draft_id}", response_model=ResponseModel[QuickCaptureMessage])
def discard(
    draft_id: int,
    member: Member = Depends(get_shortcut_member),
    service: QuickCaptureService = Depends(get_quick_capture_service),
) -> ResponseModel[QuickCaptureMessage]:
    """Discard the draft and its image."""
    service.discard(member, draft_id)
    return ResponseModel(data=QuickCaptureMessage(message="Descartado"))
