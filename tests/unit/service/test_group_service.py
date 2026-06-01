"""Unit tests for GroupService."""

from unittest.mock import MagicMock

import pytest

from template.domain.models.group import Group, GroupStatus, GroupType
from template.service_layer.group_service import GroupService


def _make_group(id=1, name="Test", status=GroupStatus.ACTIVE):
    return Group(id=id, name=name, status=status)


def _make_personal_group():
    return Group(id=10, name="Personal", status=GroupStatus.ACTIVE, group_type=GroupType.PERSONAL, owner_member_id=1)


def test_create_group_adds_creator_as_member():
    repo = MagicMock()
    repo.create.return_value = _make_group(id=5, name="My Group")
    svc = GroupService(repo)

    svc.create(name="My Group", creator_member_id=42)

    repo.create.assert_called_once_with("My Group")
    repo.add_member.assert_called_once_with(5, 42)


def test_leave_group_blocked_when_balance_nonzero():
    repo = MagicMock()
    repo.get.return_value = _make_group()
    repo.is_member.return_value = True
    svc = GroupService(repo)

    with pytest.raises(ValueError, match="balance"):
        svc.leave(group_id=1, member_id=42, member_balance=10.5)


def test_leave_group_allowed_when_balance_zero():
    repo = MagicMock()
    repo.get.return_value = _make_group()
    repo.is_member.return_value = True
    svc = GroupService(repo)

    svc.leave(group_id=1, member_id=42, member_balance=0.0)
    repo.remove_member.assert_called_once_with(1, 42)


def test_get_group_returns_none_for_missing():
    repo = MagicMock()
    repo.get.return_value = None
    svc = GroupService(repo)
    assert svc.get(999) is None


# ---------------------------------------------------------------------------
# _assert_not_personal
# ---------------------------------------------------------------------------


def test_assert_not_personal_raises_for_personal_group():
    repo = MagicMock()
    repo.get.return_value = _make_personal_group()
    svc = GroupService(repo)
    with pytest.raises(ValueError, match="personal"):
        svc._assert_not_personal(10)


def test_assert_not_personal_raises_for_missing_group():
    repo = MagicMock()
    repo.get.return_value = None
    svc = GroupService(repo)
    with pytest.raises(ValueError, match="not found"):
        svc._assert_not_personal(999)


def test_assert_not_personal_passes_for_regular_group():
    repo = MagicMock()
    repo.get.return_value = _make_group()
    svc = GroupService(repo)
    svc._assert_not_personal(1)  # should not raise


# ---------------------------------------------------------------------------
# get_or_create_personal_group
# ---------------------------------------------------------------------------


def test_get_or_create_personal_group_creates_when_none():
    repo = MagicMock()
    repo.get_personal_for_owner.return_value = None
    created = _make_personal_group()
    repo.create.return_value = created
    svc = GroupService(repo)

    result = svc.get_or_create_personal_group(member_id=1)

    repo.create.assert_called_once_with(
        name="Personal",
        group_type=GroupType.PERSONAL,
        owner_member_id=1,
    )
    repo.add_member.assert_called_once_with(created.id, 1)
    assert result == created


def test_get_or_create_personal_group_returns_existing():
    repo = MagicMock()
    existing = _make_personal_group()
    repo.get_personal_for_owner.return_value = existing
    svc = GroupService(repo)

    result = svc.get_or_create_personal_group(member_id=1)

    repo.create.assert_not_called()
    assert result == existing


# ---------------------------------------------------------------------------
# leave / close / delete blocked for personal group
# ---------------------------------------------------------------------------


def test_leave_personal_group_blocked():
    repo = MagicMock()
    repo.get.return_value = _make_personal_group()
    svc = GroupService(repo)
    with pytest.raises(ValueError, match="personal"):
        svc.leave(group_id=10, member_id=1, member_balance=0.0)


def test_close_personal_group_blocked():
    repo = MagicMock()
    repo.get.return_value = _make_personal_group()
    svc = GroupService(repo)
    with pytest.raises(ValueError, match="personal"):
        svc.close(group_id=10)


def test_delete_personal_group_blocked():
    repo = MagicMock()
    repo.get.return_value = _make_personal_group()
    svc = GroupService(repo)
    with pytest.raises(ValueError, match="personal"):
        svc.delete(group_id=10)
