import sqlite3
import logging
import httpx
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────
DB_PATH = "bot_database.db"
BOT_TOKEN = "8746874676:AAHhMQThSPHCylr8Cbeo5pMlLP86gOS3ZYw"
ADMIN_ID = 8084057668
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app) # Taaki Vercel se request aa sake

# ─────────────────────────────────────────────────────────────────────────────
# Database Helpers
# ─────────────────────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def ensure_tables():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT DEFAULT '',
                full_name TEXT DEFAULT '',
                credits INTEGER DEFAULT 5,
                is_blocked INTEGER DEFAULT 0,
                total_runs INTEGER DEFAULT 0,
                joined_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS payment_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                pack_name TEXT NOT NULL,
                amount_inr INTEGER NOT NULL,
                credits INTEGER NOT NULL,
                txn_id TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TEXT DEFAULT (datetime('now'))
            );
        """)
        conn.commit()

# ─────────────────────────────────────────────────────────────────────────────
# Telegram Helper
# ─────────────────────────────────────────────────────────────────────────────
async def send_telegram_message(chat_id, text):
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(TELEGRAM_API, json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
            })
    except Exception as e:
        logger.error(f"Telegram Notification Failed: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "time": datetime.utcnow().isoformat()})

@app.route('/user/<int:user_id>', methods=['GET'])
def get_user(user_id):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if not user:
        return jsonify({"error": "User not found"}), 404
    
    user_dict = dict(user)
    # Simple plan logic
    credits = user_dict['credits']
    plan = "👑 Master" if credits >= 1000 else "🔥 Pro" if credits >= 400 else "🧊 Starter" if credits >= 50 else "🆓 Free"
    
    return jsonify({
        "user_id": user_dict['user_id'],
        "username": user_dict['username'],
        "credits": user_dict['credits'],
        "plan": plan,
        "total_runs": user_dict['total_runs']
    })

@app.route('/notify_payment', methods=['POST'])
async def notify_payment():
    data = request.json
    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO payment_requests (user_id, pack_name, amount_inr, credits, txn_id) VALUES (?,?,?,?,?)",
                (data['user_id'], data['pack_name'], data['amount_inr'], data['credits'], data['txn_id'])
            )
            conn.commit()

        # Admin Notification
        admin_msg = (
            f"💰 <b>New Payment Request</b>\n"
            f"👤 User: {data.get('full_name', 'Unknown')} (<code>{data['user_id']}</code>)\n"
            f"📦 Pack: {data['pack_name']}\n"
            f"₹ Amount: <b>₹{data['amount_inr']}</b>\n"
            f"🔖 TXN ID: <code>{data['txn_id']}</code>\n\n"
            f"Approve: <code>/add_credits {data['user_id']} {data['credits']}</code>"
        )
        await send_telegram_message(ADMIN_ID, admin_msg)
        
        # User Notification
        await send_telegram_message(data['user_id'], "✅ Payment Request Sent! Credits will be added after manual verification.")
        
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/gift', methods=['POST'])
async def gift():
    data = request.json
    s_id, r_id, amt = data['sender_id'], data['receiver_id'], data['amount']
    
    conn = get_db()
    sender = conn.execute("SELECT credits FROM users WHERE user_id=?", (s_id,)).fetchone()
    
    if not sender or sender['credits'] < amt:
        return jsonify({"error": "Insufficient credits"}), 400
        
    try:
        conn.execute("UPDATE users SET credits = credits - ? WHERE user_id = ?", (amt, s_id))
        conn.execute("UPDATE users SET credits = credits + ? WHERE user_id = ?", (amt, r_id))
        conn.commit()
        
        await send_telegram_message(r_id, f"🎁 You received {amt} credits as a gift!")
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    ensure_tables()
    # Termux port 8000 par chalayenge
    app.run(host='0.0.0.0', port=8000)
    