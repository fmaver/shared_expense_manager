"""Unit tests for GroupRepository using in-memory SQLite."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from template.adapters.orm import Base
from template.adapters.repositories import GroupRepository
from template.domain.models.group import GroupStatus


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as s:
        yield s


def test_create_and_get_group(session):
    repo = GroupRepository(session)
    group = repo.create("Fran & Guada")
    session.commit()

    fetched = repo.get(group.id)
    assert fetched is not None
    assert fetched.name == "Fran & Guada"
    assert fetched.status == GroupStatus.ACTIVE


def test_add_and_check_membership(session):
    from template.adapters.orm import MemberModel
    from template.domain.models.enums import NotificationType

    member = MemberModel(name="Fran", telephone="5491100000001", email="fran@test.com",
                         notification_preference=NotificationType.NONE)
    session.add(member)
    session.flush()

    repo = GroupRepository(session)
    group = repo.create("Test Group")
    session.flush()

    repo.add_member(group.id, member.id)
    session.commit()

    assert repo.is_member(group.id, member.id) is True
    assert repo.is_member(group.id, 9999) is False


def test_list_groups_for_member(session):
    from template.adapters.orm import MemberModel
    from template.domain.models.enums import NotificationType

    member = MemberModel(name="Guada", telephone="5491100000002", email="guada@test.com",
                         notification_preference=NotificationType.NONE)
    session.add(member)
    session.flush()

    repo = GroupRepository(session)
    g1 = repo.create("Group One")
    g2 = repo.create("Group Two")
    session.flush()

    repo.add_member(g1.id, member.id)
    session.commit()

    groups = repo.list_for_member(member.id)
    assert len(groups) == 1
    assert groups[0].name == "Group One"
