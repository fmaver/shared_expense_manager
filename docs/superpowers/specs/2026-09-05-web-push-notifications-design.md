# Web push notifications — design

**Date:** 2026-09-05
**Status:** awaiting review
**Driver:** WhatsApp free-form replies end in October 2026. Nobody may end up with no channel.

## Verified against live documentation (2026-09-05)

The backlog entry for this said its platform claims needed re-checking before designing. They
were re-checked:

- **Web Push is not supported in Safari on iOS — only for home-screen web apps.** Adding the
  app to the Home Screen is a hard prerequisite; there is no way around it, and no amount of
  code changes it. ([WebKit](https://webkit.org/blog/13878/web-push-for-web-apps-on-ios-and-ipados/))
- **Declarative Web Push (iOS/iPadOS 18.4+) can show notifications without a service worker.**
  This corrects the backlog, which asserted a service worker was an unconditional prerequisite.
  ([WebKit](https://webkit.org/blog/16535/meet-declarative-web-push/))
- A service worker is still required by the classic Push API, which is what Android Chrome and
  iOS before 18.4 use. ([MDN](https://developer.mozilla.org/en-US/docs/Web/API/Push_API))

## The coverage problem, and the decision

Push reaches only members who installed the app. Someone using the web app in Safari — which
includes everyone arriving through an invitation link — gets nothing. Replacing WhatsApp with
push alone would silently drop those people in October.

**Decision:** route per member, per event.

| Member state | Channel |
|---|---|
| `notification_preference == NONE` | nothing — an explicit choice, still respected |
| has an active push subscription | **push** |
| otherwise | their existing preference (email via Brevo, or WhatsApp while it lasts) |

Push replaces the channel for installed members rather than adding to it, so nobody is
notified twice. Email keeps covering everyone else, which is what actually closes the October
gap. An install prompt encourages installation without depending on it.

## Data

`push_subscriptions`: `id`, `member_id` (FK), `endpoint` (unique), `p256dh`, `auth`,
`created_at`, `last_used_at`, `failure_count`. Migration `m16_push_subscriptions`,
`down_revision = m15_archive_group_memberships`.

One member can hold several subscriptions — phone plus laptop is normal — so this is a table,
not a column. A subscription is deleted when the push service answers **404 or 410 Gone**,
which is how a browser tells you the subscription is dead; anything else is a transient error
and is retried later rather than losing the device.

## The service worker, and the risk it usually brings

A service worker introduces stale-bundle risk — during this project a phone already served an
old build once. **This one registers no `fetch` handler and caches nothing.** It handles
`push` and `notificationclick` only. A service worker that never intercepts requests cannot
serve a stale asset, so the usual downside does not apply here.

Declarative Web Push is deliberately **not** used in this pass: it only helps iOS 18.4+, while
the service-worker path covers Android and older iOS as well. One mechanism is easier to reason
about than two. Revisit if the SW ever becomes a problem.

## Backend

- `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` / `VAPID_SUBJECT` env vars; `pywebpush` (2.5.0) sends.
- `GET /api/v1/push/public-key` — the browser needs it to subscribe.
- `POST /api/v1/push/subscribe` / `DELETE /api/v1/push/subscribe` — register and remove a device.
- `PushService.send_to_member(member_id, title, body, url)` — fans out to that member's devices,
  prunes dead ones.
- `NotificationService` gains the routing rule above. **Everything it already does stays**:
  the involvement check that skips members an expense does not concern, the archived-group
  filter, and the personal-group suppression. Push is a new pipe on the existing decisions, not
  a new set of decisions.

## Scope of this pass

Infrastructure plus **one** event — expense created — end to end. Once a notification actually
lands on the phone, the remaining events are repetitive:

- expense/transfer created, updated, deleted
- settlement and unsettle
- invitations, joins, and a **ghost member being claimed** (irreversible, currently silent)
- an end-of-month reminder for an unsettled balance — the only one needing a scheduled job

## Testing

SQLite unit tests: routing picks push when a subscription exists and email when it does not;
`NONE` still means nothing; a 410 deletes that subscription while a 500 keeps it; a member with
two devices gets two sends. The web-push call itself is mocked — the tests must not depend on a
network or on VAPID keys.

Integration tests for subscribe/unsubscribe, verified in CI.

## Out of scope

- Notification preferences per event type.
- Grouping or rate-limiting bursts.
- Declarative Web Push.
