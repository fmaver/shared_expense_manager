"""Dependency functions for the application."""

from fastapi import Depends
from sqlalchemy.orm import Session

from template.adapters.database import get_db
from template.adapters.repositories import (
    ChatSessionRepository,
    GroupRepository,
    MemberRepository,
    ProcessedMessageRepository,
    SQLAlchemyExpenseRepository,
)
from template.domain.models.repository import ExpenseRepository
from template.service_layer.expense_service import ExpenseService
from template.service_layer.group_service import GroupService
from template.service_layer.member_service import MemberService
from template.service_layer.whatsapp_client import MetaWhatsAppClient, WhatsAppClient


def get_repository(db: Session = Depends(get_db)) -> ExpenseRepository:
    """Get repository instance."""
    return SQLAlchemyExpenseRepository(db)


def get_member_repository(db: Session = Depends(get_db)) -> MemberRepository:
    """Get member repository instance."""
    return MemberRepository(db)


def get_group_repository(db: Session = Depends(get_db)) -> GroupRepository:
    """Get group repository instance."""
    return GroupRepository(db)


def get_group_service(
    group_repo: GroupRepository = Depends(get_group_repository),
) -> GroupService:
    """Get group service instance."""
    return GroupService(group_repo)


def get_expense_service(
    group_id: int,
    repository: ExpenseRepository = Depends(get_repository),
    group_repo: GroupRepository = Depends(get_group_repository),
) -> ExpenseService:
    """Get expense service instance scoped to a group."""
    return ExpenseService(repository, group_id=group_id, group_repo=group_repo)


def get_member_service(
    repository: MemberRepository = Depends(get_member_repository),
) -> MemberService:
    """Get member service instance."""
    return MemberService(repository)


def get_whatsapp_client() -> WhatsAppClient:
    """Get WhatsApp client instance."""
    return MetaWhatsAppClient()


def get_chat_session_repository(db: Session = Depends(get_db)) -> ChatSessionRepository:
    """Get chat session repository instance."""
    return ChatSessionRepository(db)


def get_processed_message_repository(db: Session = Depends(get_db)) -> ProcessedMessageRepository:
    """Get processed message repository instance."""
    return ProcessedMessageRepository(db)
