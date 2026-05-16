"""Unit tests for Group domain model."""
import pytest
from template.domain.models.group import Group, GroupStatus, GroupType


def test_group_defaults_to_active_regular():
    group = Group(id=1, name="Fran & Guada")
    assert group.status == GroupStatus.ACTIVE
    assert group.group_type == GroupType.REGULAR
    assert group.owner_member_id is None


def test_group_name_required():
    with pytest.raises(Exception):
        Group(id=1, name="")


def test_personal_group_requires_owner():
    group = Group(id=2, name="Mis gastos", group_type=GroupType.PERSONAL, owner_member_id=1)
    assert group.owner_member_id == 1
