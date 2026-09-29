# SMC Alerter

Forwards signals from the configured Telegram model bot and delivers Telegram cards plus urgent ntfy pushes. The signal model and parser are unchanged.

## Run

Use Python 3.11 or newer. Install `requirements.txt`, configure `.env`, then run `python run_services.py`. The supervisor restarts either child service if it exits. For continuous delivery, run on an always-on host; a sleeping laptop cannot deliver alerts.

Required environment variables:

- `LISTENER_BOT_TOKEN`: Telegram listener token
- `NTFY_TOPIC`: your ntfy topic
- `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELETHON_SESSION`: forwarder credentials
- `BRIDGE_GROUP_ID`: the Telegram bridge group ID
- `MODEL_BOT_USERNAME`: source bot username

Optional settings:

- `NTFY_URL`: defaults to `https://ntfy.sh`
- `ALERT_DB`: defaults to `alerts.sqlite3`. Set this to a persistent disk path on hosted deployments. Without persistent storage, deduplication and pending reminders do not survive redeployment.
- `REMINDER_SECONDS`: defaults to 60, minimum 30
- `MAX_PUSHES`: defaults to 5 total successful pushes per signal, including the first
- `ALERT_LIFETIME_SECONDS`: defaults to 900. No new attempts are started after this age, measured from local receipt.
- `ALERT_OWNER_IDS`: comma-separated Telegram user IDs allowed to acknowledge. If omitted, any member able to access the alert can acknowledge it for everyone.
- `DEBUG`: defaults to false; true logs incoming message previews in the forwarder.

## Delivery behavior

The listener accepts text signals only in the configured bridge group. It saves each Telegram message before delivering. Push and card delivery use independent workers. Temporary delivery failures are retried every 30 seconds until the alert expires. Accepted pushes repeat at the configured interval, up to the total push limit. Acknowledging the Telegram card stops subsequent reminders for everyone; an already in-flight push may still arrive. Image rendering failures fall back to a text alert with the same acknowledgement button.

The same bridge message is stored once, including across restarts. A repeated source message forwarded as a new bridge message is a new alert. Network timeouts can also cause duplicate remote deliveries if a service accepted a request before the connection failed. Service acceptance does not prove that a device displayed or sounded the notification.

## Device setup (no paid integration required)

Subscribe to the same ntfy topic on each phone and desktop. Enable Telegram notifications for the bridge group and ntfy notifications on each device. Check sound, Focus/Do Not Disturb, background activity, and battery restrictions. Configure Android ntfy high-priority notification settings where available. iOS behavior differs; an urgent priority does not guarantee bypassing silent mode or Focus. Use the ntfy web app for desktop subscriptions and allow browser notifications.

Official setup: https://docs.ntfy.sh/subscribe/phone/ and https://docs.ntfy.sh/subscribe/web/

No SMS or telephone service is configured. Public services may impose delivery limits. Free integrations do not guarantee free always-on hosting or uninterrupted delivery.

## Check

Run `python -m unittest discover -s tests`. These checks do not send real alerts. Before production, verify a sample signal, acknowledgement, reminder expiry, a service restart, and actual delivery with phones locked. Never commit `.env` or Telegram sessions.

## Situation-aware cards

Cards are rendered locally with Pillow and bundled fonts/artwork. No image-generation API runs per signal. Explicit high/extreme/volatile labels (including “very high”) select caution artwork first; otherwise LIMIT selects the patient analyst and MARKET selects the active explorer. BUY uses the green variants and SELL uses the red variants. These indicate setup context, not fill or outcome tracking. Unrecognized volatility descriptions use the order-type artwork.

Prices retain their available decimal precision. Artwork and fonts resolve relative to the module, so include the entire assets folder when deploying. Font licensing is included in assets/LICENSE_DEJAVU. The parser/model are unchanged. Tests cover all six visual selections, rendering, and small prices.
