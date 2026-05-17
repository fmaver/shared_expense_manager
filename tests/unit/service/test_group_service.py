"""Unit tests for GroupService."""

from unittest.mock import MagicMock

import pytest

from template.domain.models.group import Group, GroupStatus
from template.service_layer.group_service import GroupService


def _make_group(id=1, name="Test", status=GroupStatus.ACTIVE):
    return Group(id=id, name=name, status=status)


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
