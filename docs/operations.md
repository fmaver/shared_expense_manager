# Operations runbooks

One-time and per-environment setup steps for the `shared_expense_manager` service.

---

## SendGrid (email notifications)

Email notifications are sent via the SendGrid HTTP API (port 443). Free tier: 100 emails/day, no expiry.

### 1 — Create a SendGrid account
Go to [sendgrid.com](https://sendgrid.com) and sign up for a free account.

### 2 — Verify a sender address
SendGrid requires a verified "from" address before it will send mail.

1. In the SendGrid dashboard go to **Settings → Sender Authentication**
2. Click **Verify a Single Sender**
3. Fill in your name and the email address you want as the sender (e.g. your Gmail)
4. Click **Create** — SendGrid sends a verification email to that address
5. Open the email and click **Verify Single Sender**

### 3 — Create an API key
1. Go to **Settings → API Keys → Create API Key**
2. Name it (e.g. `shared-expenses-staging` or `shared-expenses-prod`)
3. Choose **Restricted Access**
4. Under **Mail Send** set to **Full Access**
5. Click **Create & View** — copy the key immediately (shown only once)

### 4 — Add env vars in Render
Do this for **both** the staging and production services in the Render dashboard
(**Dashboard → your service → Environment**):

| Variable | Value |
|---|---|
| `SENDGRID_API_KEY` | the API key from step 3 |
| `SENDGRID_FROM_EMAIL` | the verified sender email from step 2 |

Use a **different API key** for staging vs prod (makes it easy to revoke one without affecting the other).

### 5 — Remove old SMTP variables
Delete the following from Render if they exist (they are no longer read by the app):
`SMTP_SERVER`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`

### Disabling email
Leave `SENDGRID_API_KEY` unset (or empty) to silently skip email notifications without errors.
Useful for local dev or test environments where you don't need real emails.

---

## Staging WhatsApp setup

A separate Meta app (`shared-expense-manager-staging`) is wired to the **Render staging service** and the Meta **test phone number** (`+1 555-184-1153`, phone number ID `1170347522817754`). This lets you test end-to-end WhatsApp flows without touching production.

### WABA subscription — the step everyone forgets
Configuring a webhook URL in the Meta Developer Console only enables the GET verification handshake. To actually receive POST webhook events you must also subscribe the app to your WABA:

```bash
curl -X POST \
  "https://graph.facebook.com/v17.0/<WABA_ID>/subscribed_apps" \
  -H "Authorization: Bearer <TOKEN>"
# → {"success": true}
```

Do this once per Meta app (not per phone number). Without it, Meta shows the webhook as "configured" but delivers no events.

### Token management
- **Never use a temporary user token** for a deployed service — they expire after a few hours (Meta error code 190).
- Generate a **permanent system user token**: Business Settings → Users → System Users → select the system user → Generate New Token → select the app → grant `whatsapp_business_messaging` and `whatsapp_business_management` permissions → copy immediately.
- Validate a token before deploying: `GET https://graph.facebook.com/v17.0/me?access_token=<TOKEN>`. A working token returns `{"id": "...", "name": "..."}`.

### Phone number format
- Meta webhooks deliver numbers as `549XXXXXXXXXX` (country code 54 + digit 9 + local number).
- `replace_start()` in `whatsapp_service.py` strips the `9` → DB lookup uses `54XXXXXXXXXX`.
- Outbound messages (and the numbers stored in the DB) also use `54XXXXXXXXXX` — Meta's own API examples use this format.
- Store all telephone values in the DB **without the 9** (e.g. `541138718498`, not `5491138718498`).

### `expense_notification` template
The `expense_notification` template (locale `es_AR`) exists only in the **production** Meta app. In staging it will 404 when the 24-hour free-form window has expired. Workaround: send a message from the staging test number first to open the window, then the bot can reply with free-form text.
