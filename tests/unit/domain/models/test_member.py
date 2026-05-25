from decimal import Decimal

import pytest
from pydantic import ValidationError

from template.domain.models.member import Member


class TestMember:
    def test_create_valid_member(self):
        """
        GIVEN valid member data
        WHEN creating a Member instance
        THEN it should create successfully
        """
        member = Member(id=1, name="John Doe", telephone="+1234567890", email="john.doe@example.com")

        assert member.id == 1
        assert member.name == "John Doe"
        assert member.telephone == "+1234567890"
        assert member.email == "john.doe@example.com"

    def test_invalid_name(self):
        """
        GIVEN an invalid name (empty string)
        WHEN creating a Member instance
        THEN it should raise ValidationError
        """
        with pytest.raises(ValidationError):
            Member(id=1, name="", telephone="+1234567890", email="john.doe@example.com")

    def test_telephone_is_optional(self):
        """Stub members can be created without a telephone number."""
        member = Member(id=1, name="John Doe", telephone=None, email="john.doe@example.com", hashed_password="hash")
        assert member.telephone is None
        assert member.is_stub is False

    def test_is_stub_true_when_no_password(self):
        """A member with no hashed_password is a stub."""
        stub = Member(id=99, name="Bob", hashed_password=None)
        assert stub.is_stub is True
