"""Enums

Enums are used to define a set of named constants that can be used in your code.
"""

from enum import Enum


class PaymentType(str, Enum):
    DEBIT = "debit"
    CREDIT = "credit"


class NotificationType(str, Enum):
    """Notification type for members."""

    WHATSAPP = "WHATSAPP"
    EMAIL = "EMAIL"
    NONE = "NONE"


class InvitationChannel(str, Enum):
    EMAIL = "email"
    PHONE = "phone"
    LINK = "link"


class InvitationStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    EXPIRED = "expired"
    REVOKED = "revoked"
