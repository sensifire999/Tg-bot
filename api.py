import sqlite3
import logging
import httpx
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
import asyncio

# --- Config ---
DB_PATH = "bot_database.db"
BOT_TOKEN = "8746874676:AAHhMQThSPHCylr8Cbeo5pMlLP86gOS3ZYw"
ADMIN_ID = 8084057668
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

app = Flask(__name__)
CORS(app)

# --- Database Setup (Bahut Zaroori) ---
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# Server start hote hi table banane ke liye
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

# --- Sync Telegram Message (Render ke liye asaan) ---
def send_telegram_sync(chat_id, text):
    try:
        with httpx.Client(timeout=10) as client:
            client.post(TELEGRAM_API, json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
            })
    except Exception as e:
        print(f"Error: {e}")

# --- Routes ---

@app.route('/user/<int:user_id>', methods=['GET'])
def get_user(user_id):
    try:
        with get_db() as conn:
            user = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
            if not user:
                # Agar user nahi hai toh naya bana do (Silent Registration)
                conn.execute("INSERT INTO users (user_id) VALUES (?)", (user_id,))
                conn.commit()
                return jsonify({"user_id": user_id, "credits": 5, "plan": "Free", "total_runs": 0})
            
            u = dict(user)
            plan = "👑 Master" if u['credits'] >= 1000 else "🔥 Pro" if u['credits'] >= 400 else "🧊 Starter" if u['credits'] >= 50 else "🆓 Free"
            return jsonify({"user_id": u['user_id'], "credits": u['credits'], "plan": plan, "total_runs": u['total_runs']})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/notify_payment', methods=['POST'])
def notify_payment():
    data = request.json
    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO payment_requests (user_id, pack_name, amount_inr, credits, txn_id) VALUES (?,?,?,?,?)",
                (data['user_id'], data['pack_name'], data['amount_inr'], data['credits'], data['txn_id'])
            )
            conn.commit()

        msg = f"💰 <b>New Payment!</b>\nID: <code>{data['user_id']}</code>\nPack: {data['pack_name']}\nTXN: {data['txn_id']}"
        send_telegram_sync(ADMIN_ID, msg)
        send_telegram_sync(data['user_id'], "✅ Payment request received!")
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Render ke liye ye line zaroori hai
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
