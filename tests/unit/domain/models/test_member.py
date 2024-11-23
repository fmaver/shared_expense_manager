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
        member = Member(id=1, name="John Doe", telephone="+1234567890")

        assert member.id == 1
        assert member.name == "John Doe"
        assert member.telephone == "+1234567890"

    def test_invalid_name(self):
        """
        GIVEN an invalid name (empty string)
        WHEN creating a Member instance
        THEN it should raise ValidationError
        """
        with pytest.raises(ValidationError):
            Member(id=1, name="", telephone="+1234567890")

    def test_invalid_telephone(self):
        """
        GIVEN an invalid telephone number
        WHEN creating a Member instance
        THEN it should raise ValidationError
        """
        with pytest.raises(ValidationError):
            Member(id=1, name="John Doe", telephone="invalid")
