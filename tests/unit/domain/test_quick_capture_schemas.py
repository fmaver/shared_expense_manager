"""Quick-capture timestamps reach the browser as UTC, with an explicit offset.

The ORM stores them as naive UTC (`datetime.utcnow`). Sent without an offset, the browser
parsed them as local time and "hace X" was off by the UTC offset (3 hours in Argentina).
"""

from datetime import date, datetime, timedelta, timezone

from template.domain.schemas.quick_capture import (
    DraftResponse,
    ShortcutTokenIssued,
    ShortcutTokenStatus,
)

NAIVE = datetime(2026, 11, 14, 12, 30, 0)


def _has_utc_offset(value: str) -> bool:
    return value.endswith("Z") or value.endswith("+00:00")


def test_draft_created_at_is_serialised_as_utc():
    draft = DraftResponse(id=1, has_image=False, created_at=NAIVE, date=date(2026, 11, 14))

    wire = draft.model_dump(mode="json", by_alias=True)

    assert _has_utc_offset(wire["createdAt"]), wire["createdAt"]
    assert wire["createdAt"].startswith("2026-11-14T12:30:00")
    assert wire["date"] == "2026-11-14"


def test_shortcut_token_timestamps_are_serialised_as_utc():
    status = ShortcutTokenStatus(connected=True, prefix="jrn_abcd", created_at=NAIVE, last_used_at=NAIVE)
    issued = ShortcutTokenIssued(token="t", prefix="p", created_at=NAIVE)

    wire = status.model_dump(mode="json", by_alias=True)

    assert _has_utc_offset(wire["createdAt"])
    assert _has_utc_offset(wire["lastUsedAt"])
    assert _has_utc_offset(issued.model_dump(mode="json", by_alias=True)["createdAt"])
    assert ShortcutTokenStatus(connected=False).model_dump(mode="json", by_alias=True).get("lastUsedAt") is None


def test_aware_values_are_converted_not_relabelled():
    argentina = timezone(timedelta(hours=-3))
    issued = ShortcutTokenIssued(token="t", prefix="p", created_at=datetime(2026, 11, 14, 9, 30, tzinfo=argentina))

    assert issued.model_dump(mode="json", by_alias=True)["createdAt"].startswith("2026-11-14T12:30:00")
