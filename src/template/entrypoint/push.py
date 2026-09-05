"""Push subscription endpoints.

A browser subscribes with the server's VAPID public key, then hands back an endpoint plus two
keys. Those identify one device; a member may register several.
"""

import os

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from template.adapters.database import get_db
from template.adapters.repositories import PushSubscriptionRepository
from template.domain.schema_model import CamelCaseModel, ResponseModel
from template.service_layer.auth_service import get_current_member

router = APIRouter(prefix="/push", tags=["Push"])


class PushPublicKeyResponse(CamelCaseModel):
    """The VAPID public key a browser needs in order to subscribe."""

    public_key: str


class PushSubscriptionRequest(CamelCaseModel):
    """What PushManager.subscribe() hands back, flattened."""

    endpoint: str
    p256dh: str
    auth: str


@router.get("/public-key", response_model=ResponseModel[PushPublicKeyResponse])
def get_public_key(_=Depends(get_current_member)) -> ResponseModel[PushPublicKeyResponse]:
    """Return the VAPID public key. 503 when push is not configured on this deployment."""
    public_key = os.getenv("VAPID_PUBLIC_KEY")
    if not public_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Push notifications are not configured on this server",
        )
    return ResponseModel(data=PushPublicKeyResponse(public_key=public_key))


@router.post("/subscribe", status_code=status.HTTP_204_NO_CONTENT)
def subscribe(
    data: PushSubscriptionRequest,
    current_member=Depends(get_current_member),
    db: Session = Depends(get_db),
) -> None:
    """Register this browser for push. Re-subscribing the same endpoint updates it."""
    PushSubscriptionRepository(db).save(
        member_id=current_member.id,
        endpoint=data.endpoint,
        p256dh=data.p256dh,
        auth=data.auth,
    )


@router.delete("/subscribe", status_code=status.HTTP_204_NO_CONTENT)
def unsubscribe(
    data: PushSubscriptionRequest,
    current_member=Depends(get_current_member),
    db: Session = Depends(get_db),
) -> None:
    """Stop push on this device. Scoped to the caller so one member cannot remove another's."""
    PushSubscriptionRepository(db).delete_for_member(current_member.id, data.endpoint)
