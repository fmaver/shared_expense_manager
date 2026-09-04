"""Ghost members: adding one by name, and the rules for claiming one — in-memory SQLite.

`make integration` cannot run on the development machine and must not be pointed at staging,
whose conftest truncates tables. These tests give the claim logic — the security surface of
the feature — a real local RED-GREEN cycle against actual rows.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from template.adapters.orm import Base, GroupModel, MemberModel
from template.adapters.repositories import GroupRepository, MemberRepository
from template.domain.models.group import GroupStatus, GroupType
from template.service_layer.group_service import GroupService

GROUP_ID = 1
OTHER_GROUP_ID = 2


@pytest.fixture()
def session():
    """Return a fresh in-memory SQLite session with all tables created."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as s:
        yield s


@pytest.fixture()
def populated_session(session):
    """Two regular groups and one full-account creator, already in the first group."""
    session.add_all(
        [
            GroupModel(id=GROUP_ID, name="Asado", status=GroupStatus.ACTIVE, group_type=GroupType.REGULAR),
            GroupModel(id=OTHER_GROUP_ID, name="Otro", status=GroupStatus.ACTIVE, group_type=GroupType.REGULAR),
            MemberModel(id=1, name="Fran", email="fran@example.com", hashed_password="hashed"),
        ]
    )
    session.commit()
    GroupRepository(session).add_member(GROUP_ID, 1)
    return session


# ---------------------------------------------------------------------------
# Adding a member by name
# ---------------------------------------------------------------------------


def test_add_named_member_creates_a_contactless_group_member(populated_session):
    """A name is enough: the member joins the group carrying no contact details."""
    service = GroupService(GroupRepository(populated_session))
    member_repo = MemberRepository(populated_session)

    ghost = service.add_named_member(GROUP_ID, "Guada", member_repo)

    assert ghost.name == "Guada"
    assert ghost.email is None
    assert ghost.telephone is None
    assert ghost.is_stub is True
    assert "Guada" in [m.name for m in service.list_members(GROUP_ID)]


def test_add_named_member_is_rejected_for_a_personal_group(populated_session):
    """Personal groups hold exactly one person; ghosts make no sense there."""
    populated_session.add(GroupModel(id=3, name="Personal", status=GroupStatus.ACTIVE, group_type=GroupType.PERSONAL))
    populated_session.commit()
    service = GroupService(GroupRepository(populated_session))

    with pytest.raises(ValueError):
        service.add_named_member(3, "Guada", MemberRepository(populated_session))


# ---------------------------------------------------------------------------
# Which members may be claimed through a join link
# ---------------------------------------------------------------------------


def _claimable_names(session, group_id: int) -> list[str]:
    from template.service_layer.invitation_service import claimable_members

    return [m.name for m in claimable_members(GroupRepository(session), group_id)]


def test_only_contactless_stubs_are_claimable(populated_session):
    """Invited stubs carry a contact detail and must never be claimable.

    Otherwise anyone holding the join link could seize an invitation addressed to
    someone else.
    """
    group_repo = GroupRepository(populated_session)
    member_repo = MemberRepository(populated_session)

    ghost = member_repo.create_stub(name="Guada")
    by_email = member_repo.create_stub(name="Ivi", email="ivi@example.com")
    by_phone = member_repo.create_stub(name="Sol", telephone="5411999999")
    for member in (ghost, by_email, by_phone):
        group_repo.add_member(GROUP_ID, member.id)

    assert _claimable_names(populated_session, GROUP_ID) == ["Guada"]


def test_full_account_members_are_not_claimable(populated_session):
    """The creator has a password and cannot be taken over."""
    assert "Fran" not in _claimable_names(populated_session, GROUP_ID)


def test_claimable_members_are_scoped_to_the_group(populated_session):
    """A ghost in another group is not offered by this group's link."""
    group_repo = GroupRepository(populated_session)
    outsider = MemberRepository(populated_session).create_stub(name="Ajeno")
    group_repo.add_member(OTHER_GROUP_ID, outsider.id)

    assert _claimable_names(populated_session, GROUP_ID) == []


# ---------------------------------------------------------------------------
# Joining with an existing account
# ---------------------------------------------------------------------------


def _join_service(session):
    from template.adapters.repositories import GroupJoinLinkRepository
    from template.service_layer.invitation_service import GroupJoinLinkService

    return GroupJoinLinkService(
        group_repo=GroupRepository(session),
        member_repo=MemberRepository(session),
        join_link_repo=GroupJoinLinkRepository(session),
        app_base_url="http://localhost:5173",
    )


def _make_token(session, creator_id: int = 1) -> str:
    return _join_service(session).get_or_create_link(GROUP_ID, creator_id).token


def _existing_account(session, name="Guada", email="guada@example.com"):
    member = MemberRepository(session).create_stub(name=name, email=email)
    return MemberRepository(session).claim_stub(member.id, email, "hashed")


def test_authenticated_join_adds_the_caller_without_a_password(populated_session):
    """A logged-in user joins with their JWT — no name, email or password in the body."""
    joiner = _existing_account(populated_session)
    token = _make_token(populated_session)

    result = _join_service(populated_session).register_and_join(token=token, current_member=joiner)

    assert result.id == joiner.id
    assert joiner.id in [m.id for m in GroupRepository(populated_session).list_members(GROUP_ID)]


def test_authenticated_join_with_claim_merges_the_ghost(populated_session):
    """Claiming as an existing account absorbs the ghost instead of creating a member."""
    group_repo = GroupRepository(populated_session)
    ghost = MemberRepository(populated_session).create_stub(name="Guada")
    group_repo.add_member(GROUP_ID, ghost.id)
    joiner = _existing_account(populated_session, name="Guada real", email="real@example.com")
    token = _make_token(populated_session)

    result = _join_service(populated_session).register_and_join(
        token=token, claim_member_id=ghost.id, current_member=joiner
    )

    assert result.id == joiner.id
    member_ids = [m.id for m in group_repo.list_members(GROUP_ID)]
    assert joiner.id in member_ids
    assert ghost.id not in member_ids, "the ghost must be absorbed, not left alongside"


def test_authenticated_join_is_idempotent_when_already_a_member(populated_session):
    """Re-opening the link as an existing member does not duplicate the membership."""
    joiner = _existing_account(populated_session)
    token = _make_token(populated_session)
    service = _join_service(populated_session)

    service.register_and_join(token=token, current_member=joiner)
    service.register_and_join(token=token, current_member=joiner)

    members = [m.id for m in GroupRepository(populated_session).list_members(GROUP_ID)]
    assert members.count(joiner.id) == 1


def test_anonymous_join_still_requires_credentials(populated_session):
    """Without a JWT the caller must supply name, email and password."""
    token = _make_token(populated_session)

    with pytest.raises(ValueError):
        _join_service(populated_session).register_and_join(token=token, name="Nuevo")
