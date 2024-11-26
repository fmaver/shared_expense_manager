"""Member schemas"""
from template.domain.schema_model import CamelCaseModel


class MemberResponse(CamelCaseModel):
    id: int
    name: str
    telephone: str
