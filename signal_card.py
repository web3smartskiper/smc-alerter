"""Deterministic signal cards using bundled situation artwork; no network calls."""
from decimal import Decimal
from io import BytesIO
from pathlib import Path
import re
from PIL import Image, ImageDraw, ImageFont, ImageOps

ASSETS = Path(__file__).resolve().parent / 'assets'


def situation(signal):
    direction = str(signal['direction']).upper()
    vol = str(signal.get('volatility', '')).strip().lower()
    # Only explicit source labels trigger the caution artwork, not numeric guesses.
    caution = bool(re.match(r'^(?:very\s+)?(?:high|extreme|volatile)\b', vol))
    pose = 'caution' if caution else ('waiting' if signal['order_type'].upper() == 'LIMIT' else 'active')
    return direction, pose


def price(value):
    number = Decimal(str(value))
    rendered = format(number, ',f')
    return rendered.rstrip('0').rstrip('.') if '.' in rendered else rendered


def generate_signal_chart(signal):
    direction, pose = situation(signal)
    buy = direction == 'BUY'
    accent = '#9cff43' if buy else '#ff6879'
    muted = '#a9b8ad'
    canvas = Image.new('RGB', (1600, 1040), '#07110c')
    with Image.open(ASSETS / 'situations.png') as atlas:
        col = {'waiting': 0, 'active': 1, 'caution': 2}[pose]
        row = 0 if buy else 1
        w, h = atlas.size
        art = atlas.crop((col*w//3, row*h//2, (col+1)*w//3, (row+1)*h//2))
        art = ImageOps.fit(art, (610, 920), centering=(0.45, 0.45))
        canvas.paste(art, (20, 100))
    # Fade illustration into the information area without changing the stored art.
    fade = Image.new('RGBA', (200, 920))
    fd = ImageDraw.Draw(fade)
    for x in range(200):
        fd.line((x, 0, x, 920), fill=(7, 17, 12, int(255*x/199)))
    canvas.paste(fade, (430, 100), fade)
    draw = ImageDraw.Draw(canvas)

    def text(x, y, value, size=28, color='white', width=None, bold=False):
        value = str(value)
        fontpath = ASSETS / ('DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf')
        font = ImageFont.truetype(str(fontpath), size)
        while width and draw.textbbox((0, 0), value, font=font)[2] > width and size > 12:
            size -= 1
            font = ImageFont.truetype(str(fontpath), size)
        draw.text((x, y), value, font=font, fill=color)

    draw.rounded_rectangle((16, 16, 1584, 1024), radius=28, outline=accent, width=2)
    text(48, 40, 'SMC ALERTER', 35, accent, bold=True)
    mode = str(signal.get('mode', 'LIVE')).upper()
    text(1080, 48, 'SAMPLE / NOT LIVE' if mode == 'SAMPLE' else f'MODE / {mode}', 23, '#ffd574', width=450, bold=True)
    text(625, 125, signal['pair'], 88, width=890, bold=True)
    draw.rounded_rectangle((625, 240, 1535, 320), radius=16, fill=accent)
    text(655, 249, f"{signal['order_type']} {direction}", 47, '#08120b', width=850, bold=True)
    text(630, 354, 'ENTRY PRICE', 24, muted, bold=True)
    text(618, 385, price(signal['entry']), 112, accent, width=920, bold=True)

    levels = [('STOP LOSS', signal['sl'], '#ff7886')]
    if signal.get('partial_tp') is not None:
        levels.append((f"PARTIAL / {signal.get('partial_pct', '')}%", signal['partial_tp'], '#c5e9aa'))
    levels.append(('TAKE PROFIT', signal['tp'], '#9cff43'))
    step = 930 // len(levels)
    for i, (label, value, color) in enumerate(levels):
        x = 615 + i*step
        draw.rounded_rectangle((x, 545, x+step-16, 690), radius=18, fill='#101f17', outline='#34583b', width=2)
        text(x+20, 565, label, 21, color, width=step-55, bold=True)
        text(x+20, 610, price(value), 43, color, width=step-55, bold=True)

    entry, sl, tp = (Decimal(str(signal[k])) for k in ('entry', 'sl', 'tp'))
    rr = f'{abs(tp-entry)/abs(entry-sl):.1f}:1' if entry != sl else 'N/A'
    stats = [('REWARD / RISK', rr), ('CONFLUENCE', f"{signal.get('confluence', 'N/A')}/10"), ('RISK', signal.get('size', 'N/A'))]
    draw.rounded_rectangle((615, 720, 1530, 853), radius=18, fill='#101f17', outline='#34583b', width=2)
    for i, (label, value) in enumerate(stats):
        x = 639+i*303
        text(x, 739, label, 20, muted, width=265, bold=True)
        text(x, 775, value, 37, width=265, bold=True)
    text(48, 950, {'waiting':'PATIENT / LIMIT SETUP', 'active':'READY / MARKET SETUP', 'caution':'CAUTION / HIGH VOLATILITY'}[pose], 21, accent, width=530, bold=True)
    text(630, 876, f"TREND  {signal.get('trend', 'N/A')}   /   VOL  {signal.get('volatility', 'N/A')}", 21, muted, width=880)
    # Bounded lines: never let lengthy confluence notes collide with the price panels.
    details = signal.get('details', [])
    for i, detail in enumerate(details[:2]):
        label = str(detail)
        if len(label) > 90:
            label = label[:87] + '…'
        text(630, 920+i*33, '• ' + label, 21, muted, width=880)
    if len(details) > 2:
        text(630, 987, f'+{len(details)-2} more confluences in source signal', 15, muted)
    output = BytesIO()
    canvas.save(output, format='PNG')
    output.seek(0)
    return output
