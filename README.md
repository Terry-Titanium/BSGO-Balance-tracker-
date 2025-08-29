# BSGO Webhook Worker (Railway)

Posts BSGO player stats and charts to one or **multiple** Discord Webhooks on a schedule.

## Quick deploy
1) Upload these files or connect a repo to Railway.
2) Set Variables:
   ```env
   WEBHOOK_URLS=https://discord.com/api/webhooks/ID1/TOKEN1,https://discord.com/api/webhooks/ID2/TOKEN2
   UPDATE_MINUTES=15
   BSGO_URL=https://bsgo.fun/Services/Identity/Account/EU
   ```
3) Railway will run the worker using the Procfile:
   ```
   worker: python tracker.py
   ```

- Each webhook gets its own last message ID file (hashed), so subsequent runs **edit** the previous message instead of posting new ones.
- Files (CSV/images) persist only while the container is running.

## Optional JSON mode
If you ever need different regions/labels per webhook, you may set `WEBHOOK_URLS` as JSON instead:
```env
WEBHOOK_URLS=[
  {"url":"https://discord.com/api/webhooks/ID1/TOKEN1","bsgo_url":"https://bsgo.fun/Services/Identity/Account/EU","label":"EU"},
  {"url":"https://discord.com/api/webhooks/ID2/TOKEN2","bsgo_url":"https://bsgo.fun/Services/Identity/Account/US","label":"US"}
]
```
