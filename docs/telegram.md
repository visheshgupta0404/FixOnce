# Incident alerts on Telegram

FixOnce sends every incident step to Telegram straight from its own process: Bot API `sendMessage`,
outgoing only, so it works behind a company firewall and needs no other service. The message says
what team memory remembered; approving the fix stays in the FixOnce page.

```
🔴 checkout is failing. checkout is failing for about 34% of requests. ...
Seen before (team memory): Pause the running batch/export job fixed it. Made it worse: Raise the DB connection pool size.
🔁 This is the 3rd time. Root cause: the nightly orders export job holds most DB connections. Permanent fix: ...
Suggested: Pause the running batch/export job. Open FixOnce to approve: http://localhost:8000

✅ checkout fixed in 9.2s with: Pause the running batch/export job. The lesson is saved to team memory.
```

## Setup (2 minutes)

1. In Telegram, message **@BotFather**, send `/newbot`, pick a name, copy the token.
2. Open your new bot and press **Start**.
3. In `.env` (never committed): `TELEGRAM_BOT_TOKEN=<token>`. Optional: `TELEGRAM_CHAT_ID=<id>`; without it,
   FixOnce messages the last chat that pressed Start.
4. Restart FixOnce and press **Break: DB connections**. "What left this machine" counts every Telegram request.

For Slack, email or a pager, `FIXONCE_WEBHOOK_URL` posts the same events as JSON (field `text` is the message;
signed with `FIXONCE_WEBHOOK_SECRET` in header `X-FixOnce-Signature: sha256=<HMAC>`).
