import os
import re
import asyncio
import json
import time
from signal import signal
import httpx
import logging
from io import BytesIO
from datetime import datetime
from dotenv import load_dotenv

from alert_store import AlertStore
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, CallbackQueryHandler, filters, ContextTypes

load_dotenv()

LISTENER_BOT_TOKEN = os.getenv("LISTENER_BOT_TOKEN")
NTFY_TOPIC = os.getenv("NTFY_TOPIC")
NTFY_URL = os.getenv("NTFY_URL", "https://ntfy.sh")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── SIGNAL PARSER ───────────────────────────────────────────────────────────

def parse_signal(text: str) -> dict | None:
    """Parse a signal message into a structured dict. Returns None if not a signal."""
    try:
        signal = {}

        # Pair and direction
        pair_match = re.search(r'([A-Z]+USDT|[A-Z]+BTC|[A-Z]+ETH|[A-Z]+BUSD):\s*(LIMIT|MARKET)\s*(BUY|SELL)', text)
        if not pair_match:
            return None
        signal['pair'] = pair_match.group(1)
        signal['order_type'] = pair_match.group(2)
        signal['direction'] = pair_match.group(3)

        # Entry
        entry_match = re.search(r'@\s*([\d.]+)', text)
        signal['entry'] = float(entry_match.group(1)) if entry_match else None

        # Stop Loss
        sl_match = re.search(r'SL:\s*([\d.]+)', text)
        signal['sl'] = float(sl_match.group(1)) if sl_match else None

        # Take Profit
        tp_match = re.search(r'TP:\s*([\d.]+)', text)
        signal['tp'] = float(tp_match.group(1)) if tp_match else None

        # Partial TP
        partial_match = re.search(r'Partial:\s*([\d.]+)\s*\(([\d.]+)%\)', text)
        if partial_match:
            signal['partial_tp'] = float(partial_match.group(1))
            signal['partial_pct'] = partial_match.group(2)

        # Confluence score
        conf_match = re.search(r'Confluence:\s*([\d.]+)/10', text)
        signal['confluence'] = conf_match.group(1) if conf_match else 'N/A'

        # Risk size
        size_match = re.search(r'Size:\s*([\d.]+%\s*risk)', text)
        signal['size'] = size_match.group(1) if size_match else 'N/A'

        # Mode
        mode_match = re.search(r'Mode:\s*(\w+)', text)
        signal['mode'] = mode_match.group(1) if mode_match else 'LIVE'

        # Volatility and trend
        vol_match = re.search(r'Vol:\s*([^\|]+)', text)
        signal['volatility'] = vol_match.group(1).strip() if vol_match else 'N/A'

        trend_match = re.search(r'Trend:\s*(\w+)', text)
        signal['trend'] = trend_match.group(1) if trend_match else 'N/A'

        # Confluence details bullet points
        details_match = re.findall(r'•\s*(.+)', text)
        signal['details'] = details_match if details_match else []

        return signal
    except Exception as e:
        logger.error(f"Parse error: {e}")
        return None


# ─── NTFY ALARM ──────────────────────────────────────────────────────────────

async def fire_alarm(signal: dict):
    """Send a loud push notification to all devices via ntfy."""
    direction_tag = "BUY" if signal['direction'] == "BUY" else "SELL"
    title = f"[{direction_tag}] {signal['pair']} {signal['direction']} SIGNAL"
    body = (
        f"Entry: {signal['entry']} | SL: {signal['sl']} | TP: {signal['tp']}\n"
        f"Confluence: {signal['confluence']}/10 | Risk: {signal['size']}\n"
        f"Mode: {signal['mode']}"
    )

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{NTFY_URL}/{NTFY_TOPIC}",
            content=body,
            headers={
                "Title": title,
                "Priority": "urgent",          # Makes it ring loudly
                "Tags": "rotating_light,chart_with_upwards_trend",
            }
        )
        response.raise_for_status()
    logger.info(f"Push accepted for {signal['pair']}")


# ─── VISUAL SIGNAL CARD ───────────────────────────────────────────────────────

from signal_card import generate_signal_chart


# ─── DURABLE DELIVERY AND ACKNOWLEDGEMENT ────────────────────────────────────

REMINDER_SECONDS = max(30, int(os.getenv("REMINDER_SECONDS", "60")))
MAX_PUSHES = max(1, int(os.getenv("MAX_PUSHES", "5")))
ALERT_LIFETIME = max(60, int(os.getenv("ALERT_LIFETIME_SECONDS", "900")))


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.text:
        return
    if message.chat_id != int(os.environ["BRIDGE_GROUP_ID"]):
        return
    parsed = parse_signal(message.text)
    if parsed:
        context.application.bot_data["store"].add(message.chat_id, message.message_id, parsed)


async def acknowledge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.message:
        return
    owners = {int(value.strip()) for value in os.getenv("ALERT_OWNER_IDS", "").split(",") if value.strip()}
    if owners and query.from_user.id not in owners:
        await query.answer("Only configured alert owners can acknowledge this signal.", show_alert=True)
        return
    alert_id = int(query.data.split(":", 1)[1])
    if context.application.bot_data["store"].acknowledge(alert_id, query.message.chat_id):
        await query.answer("Acknowledged. Further reminders stopped.")
        await query.edit_message_reply_markup(reply_markup=None)
    else:
        await query.answer("This alert is no longer available.")


async def deliver_push(store, row, parsed):
    now = time.time()
    if row["acknowledged"] or row["push_count"] >= MAX_PUSHES or row["next_push"] > now:
        return
    try:
        await fire_alarm(parsed)
    except Exception:
        logger.exception("Push delivery failed for alert %s; retrying", row["id"])
        store.update(row["id"], next_push=time.time() + 30)
    else:
        store.update(row["id"], push_count=row["push_count"] + 1,
                     next_push=time.time() + REMINDER_SECONDS)


async def deliver_card(app, store, row, parsed):
    if row["card_sent"] or row["next_card"] > time.time():
        return
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Acknowledged — stop reminders", callback_data=f"ack:{row['id']}")]])
    caption = f"{parsed['pair']} — {parsed['direction']} SETUP\nConfluence: {parsed['confluence']}/10 | Mode: {parsed['mode']}"
    try:
        # A single worker serializes matplotlib rendering, away from the Telegram event loop.
        chart = await asyncio.to_thread(generate_signal_chart, parsed)
    except Exception:
        logger.exception("Image rendering failed; sending text alert %s", row["id"])
        chart = None
    try:
        if chart is None:
            await app.bot.send_message(chat_id=row["chat_id"], text=caption + f"\nEntry: {parsed['entry']} | SL: {parsed['sl']} | TP: {parsed['tp']}", reply_markup=keyboard)
        else:
            with chart:
                await app.bot.send_photo(chat_id=row["chat_id"], photo=chart, caption=caption, reply_markup=keyboard)
        store.update(row["id"], card_sent=1)
    except Exception:
        logger.exception("Telegram delivery failed for alert %s; retrying", row["id"])
        store.update(row["id"], next_card=time.time() + 30)


async def delivery_worker(app, channel):
    store = app.bot_data["store"]
    while True:
        try:
            for row in store.pending(ALERT_LIFETIME):
                parsed = json.loads(row["payload"])
                if channel == "push":
                    await deliver_push(store, row, parsed)
                else:
                    await deliver_card(app, store, row, parsed)
        except Exception:
            logger.exception("Delivery worker error (%s)", channel)
        await asyncio.sleep(1)


async def start_workers(app):
    app.bot_data["store"] = AlertStore(os.getenv("ALERT_DB", "alerts.sqlite3"))
    app.bot_data["workers"] = [asyncio.create_task(delivery_worker(app, channel)) for channel in ("push", "card")]


async def stop_workers(app):
    for task in app.bot_data["workers"]:
        task.cancel()
    await asyncio.gather(*app.bot_data["workers"], return_exceptions=True)
    app.bot_data["store"].db.close()


def main():
    for name in ("LISTENER_BOT_TOKEN", "NTFY_TOPIC", "BRIDGE_GROUP_ID"):
        if not os.getenv(name):
            raise EnvironmentError(f"Missing required environment variable: {name}")
    int(os.environ["BRIDGE_GROUP_ID"])
    app = (ApplicationBuilder().token(LISTENER_BOT_TOKEN)
           .post_init(start_workers).post_stop(stop_workers).build())
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(acknowledge, pattern=r"^ack:\d+$"))
    logger.info("SMC alert delivery service starting")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
