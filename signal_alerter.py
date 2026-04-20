import os
import re
import asyncio
from signal import signal
import httpx
import logging
from io import BytesIO
from datetime import datetime
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

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
        await client.post(
            f"{NTFY_URL}/{NTFY_TOPIC}",
            content=body,
            headers={
                "Title": title,
                "Priority": "urgent",          # Makes it ring loudly
                "Tags": "rotating_light,chart_with_upwards_trend",
                "Sound": "alarm",              # Alarm sound on ntfy apps
            }
        )
    logger.info(f"Alarm fired for {signal['pair']}")


# ─── VISUAL SIGNAL CARD ───────────────────────────────────────────────────────

def generate_signal_chart(signal: dict) -> BytesIO:
    """Generate a clean visual signal card as an image."""
    is_buy = signal['direction'] == 'BUY'
    accent = '#00C896' if is_buy else '#FF4C61'
    bg = '#0D1117'
    card_bg = '#161B22'
    text_col = '#E6EDF3'
    muted = '#8B949E'

    fig, ax = plt.subplots(figsize=(10, 7))
    fig.patch.set_facecolor(bg)
    ax.set_facecolor(bg)
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)
    ax.axis('off')

    # Background card
    card = mpatches.FancyBboxPatch((0.2, 0.2), 9.6, 9.6,
                                    boxstyle="round,pad=0.1",
                                    facecolor=card_bg, edgecolor=accent, linewidth=2)
    ax.add_patch(card)

    # Header bar
    header = mpatches.FancyBboxPatch((0.2, 8.8), 9.6, 1.0,
                                      boxstyle="round,pad=0.05",
                                      facecolor=accent, edgecolor='none')
    ax.add_patch(header)

    # Title
    mode_tag = f"[{signal['mode']}]"
    ax.text(5, 9.35, f"{signal['pair']}  {signal['order_type']} {signal['direction']}  {mode_tag}",
            ha='center', va='center', fontsize=16, fontweight='bold',
            color='white' if is_buy else '#0D1117', fontfamily='monospace')

    # Price levels — visual ladder
    entry = signal['entry']
    sl = signal['sl']
    tp = signal['tp']
    partial = signal.get('partial_tp')

    # Normalize prices to chart Y space (between 2.5 and 8.5)
    all_prices = [p for p in [entry, sl, tp, partial] if p is not None]
    p_min, p_max = min(all_prices), max(all_prices)
    p_range = p_max - p_min if p_max != p_min else 1

    def price_to_y(p):
        return 2.5 + ((p - p_min) / p_range) * 5.5

    # Zone fills
    entry_y = price_to_y(entry)
    sl_y = price_to_y(sl)
    tp_y = price_to_y(tp)

    # SL zone (red)
    sl_zone = plt.Polygon([[1.5, entry_y], [8.5, entry_y], [8.5, sl_y], [1.5, sl_y]],
                           facecolor='#FF4C6133', edgecolor='none')
    ax.add_patch(sl_zone)

    # TP zone (green)
    tp_zone = plt.Polygon([[1.5, entry_y], [8.5, entry_y], [8.5, tp_y], [1.5, tp_y]],
                           facecolor='#00C89633', edgecolor='none')
    ax.add_patch(tp_zone)

    # Price lines
    def draw_price_line(price, label, color, style='-', lw=1.5):
        y = price_to_y(price)
        ax.plot([1.5, 8.5], [y, y], color=color, linewidth=lw, linestyle=style)
        ax.text(1.3, y, label, ha='right', va='center', fontsize=8,
                color=color, fontfamily='monospace', fontweight='bold')
        ax.text(8.7, y, f"{price:.4f}", ha='left', va='center', fontsize=8,
                color=color, fontfamily='monospace')

    draw_price_line(tp, 'TP', '#00C896', lw=2)
    if partial:
        draw_price_line(partial, f'P.TP {signal.get("partial_pct","")}%', '#7FDBCA', style='--')
    draw_price_line(entry, 'ENTRY', accent, lw=2.5)
    draw_price_line(sl, 'SL', '#FF4C61', lw=2)

    # Candle arrow
    arrow_x = 5
    if is_buy:
        ax.annotate('', xy=(arrow_x, entry_y + 0.3), xytext=(arrow_x, entry_y - 0.5),
                    arrowprops=dict(arrowstyle='->', color=accent, lw=2))
    else:
        ax.annotate('', xy=(arrow_x, entry_y - 0.3), xytext=(arrow_x, entry_y + 0.5),
                    arrowprops=dict(arrowstyle='->', color=accent, lw=2))

    # Stats row
    rr = abs(tp - entry) / abs(entry - sl) if abs(entry - sl) > 0 else 0
    stats = [
        ("CONFLUENCE", f"{signal['confluence']}/10"),
        ("R:R RATIO", f"1:{rr:.1f}"),
        ("RISK SIZE", signal['size']),
        ("VOLATILITY", signal['volatility']),
        ("TREND", signal['trend']),
    ]

    box_w = 9.2 / len(stats)
    for i, (label, val) in enumerate(stats):
        bx = 0.4 + i * box_w
        stat_box = mpatches.FancyBboxPatch((bx, 0.5), box_w - 0.1, 1.6,
                                            boxstyle="round,pad=0.05",
                                            facecolor='#21262D', edgecolor=accent, linewidth=0.8)
        ax.add_patch(stat_box)
        ax.text(bx + (box_w - 0.1) / 2, 1.65, val, ha='center', va='center',
                fontsize=9, fontweight='bold', color=accent, fontfamily='monospace')
        ax.text(bx + (box_w - 0.1) / 2, 0.9, label, ha='center', va='center',
                fontsize=6.5, color=muted, fontfamily='monospace')

    # Confluence details
    if signal['details']:
        ax.text(0.5, 2.3, 'CONFLUENCES:', fontsize=8, color=muted,
                fontfamily='monospace', va='top')
        details_text = '   '.join([f"✦ {d}" for d in signal['details'][:4]])
        ax.text(0.5, 2.0, details_text, fontsize=7.5, color=text_col,
                fontfamily='monospace', va='top', wrap=True)
        if len(signal['details']) > 4:
            extra = '   '.join([f"✦ {d}" for d in signal['details'][4:]])
            ax.text(0.5, 1.7, extra, fontsize=7.5, color=text_col,
                    fontfamily='monospace', va='top')

    # Timestamp
    ts = datetime.utcnow().strftime('%Y-%m-%d  %H:%M:%S UTC')
    ax.text(9.8, 0.1, ts, ha='right', va='bottom', fontsize=7,
            color=muted, fontfamily='monospace')

    plt.tight_layout(pad=0)
    buf = BytesIO()
    plt.savefig(buf, format='png', dpi=150, bbox_inches='tight',
                facecolor=bg, edgecolor='none')
    plt.close()
    buf.seek(0)
    return buf


# ─── TELEGRAM MESSAGE HANDLER ────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fires when a new message arrives in the chat."""
    message = update.message
    if not message or not message.text:
        return

    text = message.text
    signal = parse_signal(text)

    if signal:
        logger.info(f"Signal detected: {signal['pair']} {signal['direction']}")

        # 1. Fire loud alarm on all devices immediately
        await fire_alarm(signal)

        # 2. Generate and send visual card back to same chat
        try:
            chart_buf = generate_signal_chart(signal)
            caption = (
                f"📊 *{signal['pair']} — {signal['direction']} SETUP*\n"
                f"Confluence: `{signal['confluence']}/10` | Mode: `{signal['mode']}`"
            )
            await message.reply_photo(
                photo=chart_buf,
                caption=caption,
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Chart generation failed: {e}")


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    app = ApplicationBuilder().token(LISTENER_BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("🚀 SMC Alert Bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
