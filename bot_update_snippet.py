"""
bot_update_snippet.py
=====================
Add these changes to your existing bot.py to integrate the Telegram Mini App.

STEP 1: Set your Mini App URL (after deploying index.html + api.py)
STEP 2: Add the WebApp button to /start
STEP 3: Register the new handler

Replace YOUR_WEBAPP_URL with your actual deployed URL.
e.g. https://yourdomain.com/  or  https://your-ngrok-url.ngrok.io/
"""

# ── Add this import at the top of bot.py ─────────────────────────────────────
from telegram import WebAppInfo

# ── Replace / update your MINI_APP_URL ───────────────────────────────────────
MINI_APP_URL = "https://anand-host.vercel.app/index.html"   # ← change this


# ── Updated /start handler — paste this OVER your existing cmd_start ─────────

@registered
async def cmd_start(update, context):
    user = update.effective_user
    import database as db
    user_data = db.get_user(user.id)
    import html, math
    def esc(t): return html.escape(str(t))

    credits = user_data["credits"] if user_data else 5

    # Build keyboard with the Web App button
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🚀 Open App",
                web_app=WebAppInfo(url=MINI_APP_URL)
            )
        ],
        [
            InlineKeyboardButton("👤 Profile",  callback_data="cb_profile"),
            InlineKeyboardButton("🎟️ Redeem",   callback_data="cb_redeem"),
        ],
        [
            InlineKeyboardButton("❓ Help",     callback_data="cb_help"),
            InlineKeyboardButton("📊 My Stats", callback_data="cb_mystats"),
        ],
    ])

    text = (
        f"👋 Welcome, <b>{esc(user.full_name)}</b>!\n\n"
        f"🤖 I'm a <b>Remote Code Runner</b> bot.\n"
        f"Send me a <code>.py</code> file and I'll execute it securely.\n\n"
        f"💳 <b>Your Credits:</b> <code>{credits}</code>\n"
        f"📌 Each 60-second run block costs <b>1 credit</b>.\n\n"
        f"🚀 Tap <b>Open App</b> to buy credits and manage your account!"
    )
    from telegram.constants import ParseMode
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)


# ── Add /app command to bot.py ────────────────────────────────────────────────

async def cmd_app(update, context):
    """Send a direct link to the Mini App."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
    from telegram.constants import ParseMode
    await update.message.reply_text(
        "🚀 <b>Open the Code Runner App</b>\n\n"
        "Buy credits, gift credits, and view your execution history!",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🚀 Launch App", web_app=WebAppInfo(url=MINI_APP_URL))
        ]])
    )


# ── In your main() function, add this line with the other CommandHandlers: ────
#
#   app.add_handler(CommandHandler("app", cmd_app))
#
# ─────────────────────────────────────────────────────────────────────────────
