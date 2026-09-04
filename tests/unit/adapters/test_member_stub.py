"""Unit tests for contactless ("ghost") stub members — in-memory SQLite.

A ghost member is someone tracked in a group by name alone: no email, no telephone, no
password. They are never notified, and can later claim their own account through the group's
join link.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from template.adapters.orm import Base
from template.adapters.repositories import MemberRepository


@pytest.fixture()
def session():
    """Return a fresh in-memory SQLite session with all tables created."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as s:
        yield s


def test_create_stub_without_any_contact_details(session):
    """A ghost member is a name and nothing else."""
    repo = MemberRepository(session)

    member = repo.create_stub(name="Guada")

    assert member.name == "Guada"
    assert member.email is None
    assert member.telephone is None
    assert member.is_stub is True


def test_two_contactless_stubs_can_coexist(session):
    """Null emails must not collide under whatever unique index members.email carries."""
    repo = MemberRepository(session)

    first = repo.create_stub(name="Guada")
    second = repo.create_stub(name="Ivi")

    assert first.id != second.id


def test_stub_with_only_an_email_is_still_a_stub(session):
    """Invited stubs keep their contact detail — that is what excludes them from claiming."""
    repo = MemberRepository(session)

    member = repo.create_stub(name="Ivi", email="ivi@example.com")

    assert member.is_stub is True
    assert member.email == "ivi@example.com"
    assert member.telephone is None
