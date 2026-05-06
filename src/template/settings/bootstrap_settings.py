"""Optional bootstrap data seeded at application startup."""

import json
import logging
from typing import List, Optional

from pydantic import BaseModel, EmailStr
from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger(__name__)


class BootstrapMember(BaseModel):
    """A member to upsert on startup, keyed by email."""

    name: str
    email: EmailStr
    telephone: str


class BootstrapSettings(BaseSettings):
    """Members to seed via the MEMBERS_BOOTSTRAP_JSON env var.

    Set MEMBERS_BOOTSTRAP_JSON to a JSON array of {name, email, telephone}
    objects to seed those members on startup. Existing rows (matched by email)
    are never overwritten. When unset, no seeding occurs.
    """

    members_bootstrap_json: Optional[str] = None

    model_config = SettingsConfigDict(case_sensitive=False)

    def parse_members(self) -> List[BootstrapMember]:
        if not self.members_bootstrap_json:
            return []
        try:
            raw = json.loads(self.members_bootstrap_json)
        except json.JSONDecodeError as exc:
            log.error("Invalid MEMBERS_BOOTSTRAP_JSON; ignoring. Error: %s", exc)
            return []
        if not isinstance(raw, list):
            log.error("MEMBERS_BOOTSTRAP_JSON must be a JSON array; got %s", type(raw).__name__)
            return []
        return [BootstrapMember(**entry) for entry in raw]
