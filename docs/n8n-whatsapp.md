# Incident alerts on WhatsApp (through n8n)

FixOnce posts every incident step to one webhook (`FIXONCE_WEBHOOK_URL`). n8n turns it into a WhatsApp
message. FixOnce never holds the WhatsApp token, and the same webhook can feed Slack, email or a pager.
Approving a fix stays in the FixOnce page: a chat message cannot run anything.

What arrives on the phone (field `text` of each event):

```
🔴 checkout is failing. checkout is failing for about 34% of requests. ...
Seen before (team memory): Pause the running batch/export job fixed it. Made it worse: Raise the DB connection pool size.
Suggested: Pause the running batch/export job. Open FixOnce to approve: http://localhost:8000

✅ checkout fixed in 9.2s with: Pause the running batch/export job. The lesson is saved to team memory.
```

With Meko OFF the first message says the suggestion is a guess, and the last one says it was handed to a senior.

## 1. WhatsApp test number (Meta, about 30 minutes)

1. developers.facebook.com > My Apps > Create app > type **Business** > add the **WhatsApp** product.
2. WhatsApp > API Setup: note the **Phone number ID** of the free test number, and the **temporary access
   token** (valid 24 hours: make a fresh one on the morning of the demo).
3. Under "To", add your own phone number and confirm the code WhatsApp sends you (up to 5 numbers).
4. From that phone, send any message ("hi") to the test number. This opens the 24-hour window in which
   plain text messages are allowed. Do it again before judging.

## 2. n8n (n8n Cloud trial, or your own n8n)

1. Workflows > Import from file > `integrations/n8n/fixonce-whatsapp.json`.
2. Open **Send WhatsApp**: create a "WhatsApp API" credential with the access token and your business
   account ID; paste the Phone number ID and your number (country code, no +, e.g. 9198xxxxxxxx).
   If the import complains about the node, add a "WhatsApp Business Cloud > Send message" node by hand
   with Text body `{{ $json.body.text }}`.
3. Open **FixOnce webhook**, copy the **Production URL**, and activate the workflow.

## 3. FixOnce

In `.env` (never in the repo):

```
FIXONCE_WEBHOOK_URL=<the n8n production URL>
FIXONCE_WEBHOOK_SECRET=<any long random string, optional>
FIXONCE_PUBLIC_URL=http://localhost:8000
```

Restart FixOnce and press **Break: DB connections**. The page's "What left this machine" panel lists every
webhook request and its HTTP status.

## Payload

`POST` JSON with `event` (`incident.proposed` | `incident.resolved` | `incident.escalated`), `incident_id`,
`service`, `version`, `status`, `summary`, `meko_enabled`, `seen_before`, `confidence`, `worked_before`,
`made_it_worse`, `proposed_action`, `proposed_label`, `reason`, `attempts`, `time_to_fix_s`, `simulation`,
`url`, `text`. With a secret, header `X-FixOnce-Signature: sha256=<HMAC-SHA256 of the body>`.
