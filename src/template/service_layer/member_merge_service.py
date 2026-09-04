"""Absorb a ghost member into an existing account.

A ghost member (a stub with no email and no telephone) exists only as a name inside a group.
When the real person turns up holding a join link and already has an account, their history
must move onto that account. `claim_stub` cannot do this: it upgrades the stub's own row, which
only works when the joiner has no row of their own.

The defining property of a merge is that it **changes no amounts** — it relabels who an amount
belongs to. That is what makes rewriting even settled months correct: the arithmetic is
identical afterwards, only the owner differs.
"""

from typing import Any, Dict, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from template.adapters.orm import (
    ExpenseModel,
    GroupJoinLinkModel,
    GroupMembershipModel,
    GroupModel,
    IncomeInstanceModel,
    InvitationModel,
    MemberModel,
    MonthlyShareModel,
    RecurringGroupExpenseModel,
    RecurringIncomeModel,
    RecurringPersonalExpenseModel,
)


def remap_strategy(strategy: Optional[dict], ghost_id: int, survivor_id: int) -> Optional[dict]:
    """Return a split strategy with every reference to the ghost pointing at the survivor.

    Handles all three shapes. `participant_ids` is a list of ints; `percentages` and `amounts`
    are dicts **keyed by member id**, so it is the keys that move while the values stay put.
    When both ids appear in the same dict, their shares are added — anything else would change
    the expense total.
    """
    if not strategy:
        return strategy

    updated: Dict[str, Any] = dict(strategy)

    participants = updated.get("participant_ids")
    if isinstance(participants, list):
        remapped = [survivor_id if pid == ghost_id else pid for pid in participants]
        # dict.fromkeys preserves order while dropping the duplicate created when the survivor
        # was already a participant alongside the ghost.
        updated["participant_ids"] = list(dict.fromkeys(remapped))

    for field in ("percentages", "amounts"):
        shares = updated.get(field)
        if not isinstance(shares, dict):
            continue
        moved: Dict[str, float] = {}
        for member_key, value in shares.items():
            key = str(survivor_id) if str(member_key) == str(ghost_id) else str(member_key)
            moved[key] = moved.get(key, 0) + value
        updated[field] = moved

    return updated


class MemberMergeService:
    """Move every reference to a ghost member onto an existing account, then delete the ghost."""

    def __init__(self, session: Session):
        self.session = session

    def merge(self, ghost_id: int, survivor_id: int, group_id: int) -> None:
        """Absorb `ghost_id` into `survivor_id` within `group_id`.

        Runs as one transaction: a half-merged member — expenses repointed but the membership
        still on the ghost, or the ghost deleted while a JSON blob still names it — is worse
        than a failed merge.
        """
        if ghost_id == survivor_id:
            raise ValueError("Cannot merge a member into itself")

        ghost = self._ghost_or_raise(ghost_id)
        if self.session.get(MemberModel, survivor_id) is None:
            raise ValueError(f"Member {survivor_id} not found")
        self._assert_owns_nothing_personal(ghost_id)

        self._repoint_expenses(ghost_id, survivor_id)
        self._repoint_recurring_group_expenses(ghost_id, survivor_id)
        self._rewrite_balances(ghost_id, survivor_id)
        self._repoint_invitations(ghost_id, survivor_id)
        self._move_membership(ghost_id, survivor_id, group_id)

        self.session.delete(ghost)
        self.session.commit()

    # --- preconditions ---

    def _ghost_or_raise(self, ghost_id: int) -> MemberModel:
        """Return the member only if it is a ghost: a stub carrying no contact details."""
        ghost = self.session.get(MemberModel, ghost_id)
        if ghost is None:
            raise ValueError(f"Member {ghost_id} not found")
        if ghost.hashed_password is not None:
            raise ValueError("That member already has an account and cannot be merged")
        if ghost.email is not None or ghost.telephone is not None:
            raise ValueError("That member was invited directly and cannot be merged")
        return ghost

    def _assert_owns_nothing_personal(self, ghost_id: int) -> None:
        """Abort if the ghost owns anything only a real account can own.

        A ghost has no personal group, no income and no join links. A hit here means the row is
        not really a ghost, so the merge must abort rather than half-apply.
        """
        owned = (
            (GroupModel, GroupModel.owner_member_id, "a personal group"),
            (RecurringIncomeModel, RecurringIncomeModel.owner_member_id, "recurring income"),
            (IncomeInstanceModel, IncomeInstanceModel.owner_member_id, "income entries"),
            (
                RecurringPersonalExpenseModel,
                RecurringPersonalExpenseModel.owner_member_id,
                "recurring personal expenses",
            ),
            (GroupJoinLinkModel, GroupJoinLinkModel.created_by_member_id, "join links"),
        )
        for model, column, label in owned:
            if self.session.query(model).filter(column == ghost_id).count():
                raise ValueError(f"Refusing to merge: member {ghost_id} owns {label}")

    # --- rewrites ---

    def _repoint_expenses(self, ghost_id: int, survivor_id: int) -> None:
        """Move payer_id and rewrite the member ids embedded in split_strategy."""
        expenses = (
            self.session.query(ExpenseModel)
            .filter(or_(ExpenseModel.payer_id == ghost_id, ExpenseModel.split_strategy.isnot(None)))
            .all()
        )
        for expense in expenses:
            if expense.payer_id == ghost_id:
                expense.payer_id = survivor_id
            expense.split_strategy = remap_strategy(expense.split_strategy, ghost_id, survivor_id)

    def _repoint_recurring_group_expenses(self, ghost_id: int, survivor_id: int) -> None:
        """Templates carry their own payer and split, separate from the rows they generate."""
        for template in self.session.query(RecurringGroupExpenseModel).all():
            if template.payer_id == ghost_id:
                template.payer_id = survivor_id
            template.split_strategy = remap_strategy(template.split_strategy, ghost_id, survivor_id)

    def _rewrite_balances(self, ghost_id: int, survivor_id: int) -> None:
        """Remap the member-id keys of every monthly share's balances JSON.

        Settled months are included deliberately: `recalculate_balances` returns early when
        `is_settled`, so their balances would otherwise keep pointing at a deleted member.
        Amounts are added when both ids are present, so the total is unchanged.
        """
        for share in self.session.query(MonthlyShareModel).all():
            balances = share.balances or {}
            if str(ghost_id) not in {str(key) for key in balances}:
                continue
            moved: Dict[str, float] = {}
            for member_key, value in balances.items():
                key = str(survivor_id) if str(member_key) == str(ghost_id) else str(member_key)
                moved[key] = moved.get(key, 0) + value
            share.balances = moved

    def _repoint_invitations(self, ghost_id: int, survivor_id: int) -> None:
        """A ghost normally has no invitation, but repoint any that exist rather than orphan it."""
        for invitation in (
            self.session.query(InvitationModel)
            .filter(
                (InvitationModel.invitee_member_id == ghost_id) | (InvitationModel.accepted_by_member_id == ghost_id)
            )
            .all()
        ):
            if invitation.invitee_member_id == ghost_id:
                invitation.invitee_member_id = survivor_id
            if invitation.accepted_by_member_id == ghost_id:
                invitation.accepted_by_member_id = survivor_id

    def _move_membership(self, ghost_id: int, survivor_id: int, group_id: int) -> None:
        """Ensure the survivor is in the group exactly once, then drop the ghost's memberships."""
        survivor_memberships = (
            self.session.query(GroupMembershipModel)
            .filter(
                GroupMembershipModel.group_id == group_id,
                GroupMembershipModel.member_id == survivor_id,
            )
            .count()
        )
        if not survivor_memberships:
            self.session.add(GroupMembershipModel(group_id=group_id, member_id=survivor_id))

        self.session.query(GroupMembershipModel).filter(GroupMembershipModel.member_id == ghost_id).delete()
