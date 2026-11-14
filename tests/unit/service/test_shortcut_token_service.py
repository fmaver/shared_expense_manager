"""ShortcutTokenService: opaque token, stored only as a hash."""

import hashlib
from datetime import datetime

from template.adapters.orm import ShortcutTokenModel
from template.service_layer.auth_service import AuthService
from template.service_layer.shortcut_token_service import ShortcutTokenService


class FakeTokenRepo:
    def __init__(self):
        self.rows: list[ShortcutTokenModel] = []

    def get_active(self, member_id):
        return next((r for r in self.rows if r.member_id == member_id and r.revoked_at is None), None)

    def find_active_by_hash(self, token_hash):
        return next((r for r in self.rows if r.token_hash == token_hash and r.revoked_at is None), None)

    def revoke_all(self, member_id):
        for r in self.rows:
            if r.member_id == member_id and r.revoked_at is None:
                r.revoked_at = datetime.utcnow()

    def add(self, model):
        self.rows.append(model)

    def touch(self, model):
        model.last_used_at = datetime.utcnow()

    def commit(self):
        pass


def test_issue_returns_plain_token_once_and_stores_only_hash():
    repo = FakeTokenRepo()
    token, model = ShortcutTokenService(repo).issue(1)
    assert token.startswith("jrn_")
    assert model.token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert model.prefix == token[:8]
    assert token not in (model.token_hash, model.prefix)


def test_issue_revokes_previous():
    repo = FakeTokenRepo()
    service = ShortcutTokenService(repo)
    old, _ = service.issue(1)
    new, _ = service.issue(1)
    assert service.authenticate(old) is None
    assert service.authenticate(new) == 1
    assert len([r for r in repo.rows if r.revoked_at is None]) == 1


def test_authenticate_rejects_revoked_and_non_jrn():
    repo = FakeTokenRepo()
    service = ShortcutTokenService(repo)
    token, _ = service.issue(1)
    assert service.authenticate(token) == 1
    assert repo.get_active(1).last_used_at is not None
    service.revoke(1)
    assert service.authenticate(token) is None
    assert service.status(1) is None
    jwt = AuthService(None).create_access_token({"sub": "a@b.c"})  # type: ignore[arg-type]
    assert service.authenticate(jwt) is None
    assert service.authenticate("jrn_unknown") is None
