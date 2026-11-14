"""Token personal del atajo de iOS.

Opaco (``jrn_`` + 32 bytes urlsafe), guardado solo como SHA-256, sin vencimiento, uno activo por
miembro. No es un JWT: ``get_current_member`` no lo acepta, y esta dependencia no acepta JWT.
"""

import hashlib
import hmac
import secrets
from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from template.adapters.database import get_db
from template.adapters.orm import ShortcutTokenModel
from template.adapters.repositories import MemberRepository, ShortcutTokenRepository
from template.domain.models.member import Member

TOKEN_PREFIX = "jrn_"
VISIBLE_PREFIX_LENGTH = 8


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class ShortcutTokenService:
    def __init__(self, repo: ShortcutTokenRepository):
        self.repo = repo

    def issue(self, member_id: int) -> tuple[str, ShortcutTokenModel]:
        """Revoke the active token and mint a new one; the plain value is returned only here."""
        raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
        self.repo.revoke_all(member_id)
        model = ShortcutTokenModel(member_id=member_id, token_hash=_hash(raw), prefix=raw[:VISIBLE_PREFIX_LENGTH])
        self.repo.add(model)
        self.repo.commit()
        return raw, model

    def status(self, member_id: int) -> Optional[ShortcutTokenModel]:
        """The member's active token row, if any."""
        return self.repo.get_active(member_id)

    def revoke(self, member_id: int) -> None:
        """Revoke the member's active token."""
        self.repo.revoke_all(member_id)
        self.repo.commit()

    def authenticate(self, raw: str) -> Optional[int]:
        """member_id for a live token (recording its use); None otherwise."""
        if not raw.startswith(TOKEN_PREFIX):
            return None
        digest = _hash(raw)
        model = self.repo.find_active_by_hash(digest)
        if model is None or not hmac.compare_digest(model.token_hash, digest):
            return None
        self.repo.touch(model)
        self.repo.commit()
        return model.member_id


def get_shortcut_member(authorization: Optional[str] = Header(default=None), db: Session = Depends(get_db)) -> Member:
    """Authenticate a shortcut request by its ``Bearer jrn_...`` token."""
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    scheme, _, raw = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not raw:
        raise unauthorized
    member_id = ShortcutTokenService(ShortcutTokenRepository(db)).authenticate(raw.strip())
    if member_id is None:
        raise unauthorized
    member = MemberRepository(db).get(member_id)
    if member is None:
        raise unauthorized
    return member
