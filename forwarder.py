import os
from telethon.sessions import StringSession
import asyncio
from telethon import TelegramClient, events
from dotenv import load_dotenv

load_dotenv()

# ── Env validation ────────────────────────────────────────────────────────────
REQUIRED_VARS = ["TELEGRAM_API_ID", "TELEGRAM_API_HASH", "BRIDGE_GROUP_ID", "MODEL_BOT_USERNAME"]
for key in REQUIRED_VARS:
    if not os.getenv(key):
        raise EnvironmentError(f"Missing required environment variable: {key}")

API_ID             = int(os.getenv("TELEGRAM_API_ID"))
API_HASH           = os.getenv("TELEGRAM_API_HASH")
BRIDGE_GROUP_ID    = int(os.getenv("BRIDGE_GROUP_ID"))
MODEL_BOT_USERNAME = os.getenv("MODEL_BOT_USERNAME").lstrip("@")

RECONNECT_DELAY = 10
DEBUG = True  

# ── Client setup ──────────────────────────────────────────────────────────────
SESSION = os.getenv("TELETHON_SESSION", "")

client = TelegramClient(
    StringSession(SESSION),
    API_ID,
    API_HASH,
    connection_retries=5,
    timeout=30,
    device_model="Mac",
    system_version="macOS",
    app_version="1.0"
)

bridge_entity = None  # resolved at startup

# ── Debug handler (logs ALL incoming messages) ────────────────────────────────
@client.on(events.NewMessage(incoming=True))
async def debug_all(event):
    if not DEBUG:
        return
    try:
        sender    = await event.get_sender()
        username  = getattr(sender, 'username', None) or "no_username"
        sender_id = getattr(sender, 'id', 'unknown')
        chat_id   = event.chat_id
        preview   = (event.message.text or "[media / no text]")[:60]
        print(f"[DEBUG] from=@{username} (id={sender_id}) | chat={chat_id} | text={preview}")
    except Exception as e:
        print(f"[DEBUG] Could not read sender info: {e}")

# ── Forward handler ───────────────────────────────────────────────────────────
@client.on(events.NewMessage(incoming=True))
async def forward_signal(event):
    """Forward messages from the model bot to the bridge group."""
    global bridge_entity
    try:
        sender          = await event.get_sender()
        sender_username = getattr(sender, 'username', None) or ""

        if sender_username.lower() != MODEL_BOT_USERNAME.lower():
            return

        if bridge_entity is None:
            print("[ERROR] Bridge entity not resolved — cannot forward.")
            return

        await client.forward_messages(bridge_entity, event.message)
        preview = (event.message.text or "[media / no text]")[:60]
        print(f"[OK] Signal forwarded to bridge: {preview}...")

    except Exception as e:
        print(f"[ERROR] Failed to forward message: {e}")

# ── Resolve bridge group by scanning dialogs ───────────────────────────────────
async def resolve_bridge_entity():
    print("[INFO] Scanning dialogs to find bridge group...")
    async for dialog in client.iter_dialogs():
        if dialog.id == BRIDGE_GROUP_ID:
            print(f"[OK] Bridge group found: '{dialog.name}' (id={dialog.id})")
            return dialog.entity

    
    print(f"[ERROR] No dialog matched BRIDGE_GROUP_ID={BRIDGE_GROUP_ID}")
    print("[INFO] Your available groups/channels:")
    async for dialog in client.iter_dialogs():
        if dialog.is_group or dialog.is_channel:
            print(f"        name='{dialog.name}' | id={dialog.id}")
    print("[HINT] Copy the correct id above into your .env as BRIDGE_GROUP_ID")
    return None

# ── Main loop with reconnect ──────────────────────────────────────────────────
async def main():
    global bridge_entity

    await client.start()

    bridge_entity = await resolve_bridge_entity()
    if bridge_entity is None:
        return

    me = await client.get_me()
    print(f"Logged in as : @{me.username} (id={me.id})")
    print(f"Watching for : @{MODEL_BOT_USERNAME}")
    print(f"Forwarding to: {getattr(bridge_entity, 'title', BRIDGE_GROUP_ID)}")
    print(f"Debug mode   : {'ON — set DEBUG=False once working' if DEBUG else 'OFF'}")
    print("─" * 50)

    while True:
        try:
            await client.run_until_disconnected()
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[WARN] Disconnected unexpectedly: {e}")
            print(f"[INFO] Reconnecting in {RECONNECT_DELAY}s...")
            await asyncio.sleep(RECONNECT_DELAY)
            try:
                await client.connect()
                print("[INFO] Reconnected successfully.")
            except Exception as reconnect_err:
                print(f"[ERROR] Reconnect failed: {reconnect_err}")
                break

    print("Forwarder shut down.")

# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nForwarder stopped.")