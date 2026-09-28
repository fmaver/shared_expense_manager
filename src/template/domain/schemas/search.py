"""Search and unsettled-month response schemas."""

from template.domain.schema_model import CamelCaseModel


class UnsettledMonth(CamelCaseModel):
    """A past month of a group that was left unsettled."""

    year: int
    month: int
