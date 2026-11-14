"""Draft endpoints for the PWA ("carga rápida"). Auth: the normal JWT login."""

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Response,
    UploadFile,
    status,
)

from template.dependencies import get_quick_capture_service
from template.domain.models.member import Member
from template.domain.schema_model import ResponseModel
from template.domain.schemas.expense import ExpenseResponse
from template.domain.schemas.quick_capture import DraftResponse, QuickCaptureConfirm
from template.service_layer.auth_service import get_current_member
from template.service_layer.quick_capture_service import QuickCaptureService

router = APIRouter(prefix="/drafts", tags=["Drafts"])


@router.post("", response_model=ResponseModel[DraftResponse], status_code=status.HTTP_201_CREATED)
def save_for_later(
    file: UploadFile = File(...),
    member: Member = Depends(get_current_member),
    service: QuickCaptureService = Depends(get_quick_capture_service),
) -> ResponseModel[DraftResponse]:
    """ "Dejar para después": store and read a photo as a pending draft. No push."""
    return ResponseModel(data=service.save_for_later(member, file.file.read(), file.content_type or ""))


@router.get("", response_model=ResponseModel[list[DraftResponse]])
def list_drafts(
    member: Member = Depends(get_current_member),
    service: QuickCaptureService = Depends(get_quick_capture_service),
) -> ResponseModel[list[DraftResponse]]:
    """Pending drafts, oldest first."""
    return ResponseModel(data=service.list_pending_responses(member))


@router.get("/{draft_id}/image")
def get_image(
    draft_id: int,
    member: Member = Depends(get_current_member),
    service: QuickCaptureService = Depends(get_quick_capture_service),
) -> Response:
    """The draft's image, as raw bytes (outside the `{data}` envelope)."""
    content, mime = service.get_image(member, draft_id)
    return Response(content=content, media_type=mime)


@router.post("/{draft_id}/confirm", response_model=ResponseModel[ExpenseResponse])
def confirm(
    draft_id: int,
    body: QuickCaptureConfirm,
    background_tasks: BackgroundTasks,
    member: Member = Depends(get_current_member),
    service: QuickCaptureService = Depends(get_quick_capture_service),
) -> ResponseModel[ExpenseResponse]:
    """Create the expense from the draft in the chosen group."""
    return ResponseModel(data=service.confirm(member, draft_id, body.group_id, background_tasks))


@router.post("/{draft_id}/resolve", status_code=status.HTTP_204_NO_CONTENT)
def resolve(
    draft_id: int,
    member: Member = Depends(get_current_member),
    service: QuickCaptureService = Depends(get_quick_capture_service),
) -> Response:
    """The app saved the expense through its form: close the draft."""
    service.resolve(member, draft_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{draft_id}", status_code=status.HTTP_204_NO_CONTENT)
def discard(
    draft_id: int,
    member: Member = Depends(get_current_member),
    service: QuickCaptureService = Depends(get_quick_capture_service),
) -> Response:
    """Discard the draft and its image."""
    service.discard(member, draft_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
