"""Enums

Enums are used to define a set of named constants that can be used in your code.
"""

from enum import Enum


class PaymentType(str, Enum):
    DEBIT = "debit"
    CREDIT = "credit"


class NotificationType(str, Enum):
    """Notification type for members."""

    WHATSAPP = "whatsapp"
    EMAIL = "email"
    NONE = "none"
