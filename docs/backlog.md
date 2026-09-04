# Backlog — designed but not built

Ideas explored in enough depth to start from, but deliberately not implemented. Each entry
records what was **verified in the code** (with file:line) versus what still needs checking, so
a later session does not have to redo the investigation — or trust a stale claim.

Both entries below were scoped on **2026-09-04**. The platform facts about iOS need
re-verification before implementation; the code facts were read directly and are cited.

---

## 1. Persistent login — stop logging users out every 30 minutes

**The ask:** "Can the webapp save credentials like a regular app? WhatsApp never asks me to log
in again."

**This is not a platform limitation.** It is our token policy.

### Verified in the code

| Fact | Where |
|---|---|
| `ACCESS_TOKEN_EXPIRE_MINUTES = 30` | `src/template/service_layer/auth_service.py:22` |
| No refresh mechanism — the frontend stores an expiry and shows the login screen once it passes | `shared_expense_front/src/App.tsx:34`, `LoginPage.tsx:54,76` |
| `create_access_token` defaults to **15** minutes when no `expires_delta` is passed — inconsistent with the 30 above; check which callers rely on the default | `auth_service.py:122` |
| `SECRET_KEY = "your-secret-key"` hardcoded | `auth_service.py` — already flagged as known debt in `CLAUDE.md` |
| Login form markup is already correct for iOS Keychain: `autoComplete="email"` and `autoComplete="current-password"` | `LoginPage.tsx:130,137` |

So password autofill already works; the session length is the whole problem.

### Three levels, cheapest first

**Level 1 — longer token life.** Raise `ACCESS_TOKEN_EXPIRE_MINUTES` to ~30 days. Fixes the
complaint almost immediately.

> **Do not ship this without moving `SECRET_KEY` to an env var in the same change.** A 30-day
> token with a hardcoded, publicly-known signing secret is a materially worse position than a
> 30-minute one: anyone who reads the repo can mint a valid token for any member. Extending
> the lifetime multiplies the cost of that existing debt rather than adding to it linearly.
> There is also no revocation, so a leaked token stays good for its full life.

**Level 2 — refresh tokens (the proper fix).** Short access token (15–30 min) plus a long-lived
refresh token with rotation and a revocation table. Gives indefinite sessions *and* the ability
to log a device out. Needs: an `m<N>_refresh_tokens` migration, a refresh endpoint, and an axios
interceptor on the frontend that retries once on 401.

**Level 3 — passkeys / WebAuthn.** Face ID login, no password. Works in iOS home-screen web
apps. The real "native app" feel, and the largest piece of work.

### Caveat that applies at every level

`localStorage` in an iOS home-screen web app can be evicted under storage pressure, so "logged
in forever" is never a hard guarantee on iPhone. Keychain autofill (already working) is what
makes the occasional re-login painless.

### Recommended entry point

Level 1 **plus** the `SECRET_KEY` env var, as one `shipping-a-feature` change (it is auth
logic). Decide on Level 2 vs 3 later, driven by whether session revocation is ever needed.

---

## 2. Push notifications on iOS

**The ask:** native-style push on iPhone, alongside the existing WhatsApp and email channels.

**Possible, with one condition that shapes everything:** iOS web push works **only for web apps
added to the Home Screen**. It does not work in a Safari tab.

That interacts badly with the join flow: a join link always opens Safari (see "Why links cannot
open the installed app" below), so a new user is in the *browser*, where push is unavailable.
They only become reachable after deliberately installing the app.

### Verified in the code

| Fact | Where |
|---|---|
| A manifest exists with `display: standalone` and icons | `shared_expense_front/public/manifest.webmanifest` |
| **No service worker anywhere** — `grep serviceWorker src/` is empty, and no `vite-plugin-pwa` in `package.json` | prerequisite for standard web push |
| `apple-touch-icon` and `theme-color` are already set correctly | `index.html:6,14` |
| `apple-mobile-web-app-capable` and `apple-mobile-web-app-status-bar-style` are **absent** | `index.html` — the status-bar one is a real visual win given `viewport-fit=cover` is set |
| Channel model already fits: `NotificationType` is `WHATSAPP` / `EMAIL` / `NONE` — add `PUSH` | `src/template/domain/models/enums.py:14` |
| Every notification branch guards on the contact field it needs, so a new channel slots in cleanly | `src/template/service_layer/notification_service.py` |

### What it would take

1. A service worker (`vite-plugin-pwa`), configured with versioned precaching.
2. VAPID keys, and an `m<N>_push_subscriptions` migration (`endpoint`, `p256dh`, `auth`,
   `member_id`) — so this is **`shipping-a-feature`**, not a small change.
3. A sender in `notification_service.py` plus `PUSH` on `NotificationType`.
4. A permission prompt fired from a real user gesture, placed deliberately — iOS effectively
   gives one shot; a decline means the user must re-enable it in Settings.

### Reasons to think twice

- WhatsApp and email notifications already work, and the audience is family and friends already
  reachable on WhatsApp. Push mainly improves things for users who installed the app.
- **A service worker increases stale-bundle risk.** During the 2026-09-04 session a phone served
  an old bundle after a deploy; a carelessly configured SW makes that class of problem more
  likely, not less.

### Needs re-verification before designing

The exact current iOS requirements were **not** confirmed against live docs. In particular
**Declarative Web Push** (recent Safari) relaxes the service-worker requirement for simple
notifications, which could change the shape of the whole feature. Pull the current
WebKit/MDN documentation first — do not design from memory of version numbers.

---

## Why links cannot open the installed app (settled — do not re-investigate)

Asked on 2026-09-04, and the answer is a platform wall, not a gap in our code:

- **iOS: not possible.** No link capturing for home-screen web apps, no manifest field for it.
  Custom URL schemes cannot be registered by a web app; Universal Links need a real native app
  plus an `apple-app-site-association` file. Tapping a join link always opens Safari.
- **Android/Chrome: works.** In-scope https links are captured into an installed PWA.
- `scope`, `launch_handler` and `id` were considered and **rejected as not worth adding** for an
  iPhone-first audience: `scope` defaults to the directory of `start_url` (`"/"`), so setting
  `"scope": "/"` is a no-op, and Safari ignores the other two entirely.
- The only route to the real thing on iOS is a native wrapper (e.g. Capacitor) with an
  associated domain.

**The practical consequence, which is worth solving on its own:** an iOS home-screen web app has
**separate storage from Safari**. So someone who joins via a link is logged in *in Safari*, then
opens the app icon and is logged out, because the install cannot see Safari's `localStorage`.
The join response already returns an `accessToken`, so a handover is possible (a one-time code,
or accepting a token from the URL) — worth designing if the join flow feels broken on iPhone.
