"""
api.py — FastAPI backend for Remote Code Runner Telegram Mini App
=================================================================
Connects to bot_database.db (SQLite created by database.py / bot.py).

Run:
    pip install fastapi uvicorn httpx
    uvicorn api:app --host 0.0.0.0 --port 8000 --reload

Endpoints:
    GET  /user/{user_id}          — fetch user stats
    POST /notify_payment          — notify admin of a pending UPI payment
    POST /gift                    — transfer credits between users
    GET  /leaderboard             — top users by credits (bonus)
    GET  /health                  — health-check
"""

import sqlite3
import logging
import httpx
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────

DB_PATH = "bot_database.db"           # shared with bot.py / database.py
BOT_TOKEN = "8746874676:AAHhMQThSPHCylr8Cbeo5pMlLP86gOS3ZYw"
ADMIN_ID = 8084057668
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Database helpers (sync SQLite — simple & sufficient for a mini app)
# ─────────────────────────────────────────────────────────────────────────────

def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def db_fetchone(query: str, params: tuple = ()) -> Optional[dict]:
    with get_db() as conn:
        cur = conn.execute(query, params)
        row = cur.fetchone()
        return dict(row) if row else None


def db_execute(query: str, params: tuple = ()) -> int:
    """Execute a write query; returns rowcount."""
    with get_db() as conn:
        cur = conn.execute(query, params)
        conn.commit()
        return cur.rowcount


def db_fetchall(query: str, params: tuple = ()) -> list[dict]:
    with get_db() as conn:
        cur = conn.execute(query, params)
        return [dict(r) for r in cur.fetchall()]


def ensure_tables():
    """Make sure all required tables exist (idempotent)."""
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id       INTEGER PRIMARY KEY,
                username      TEXT    DEFAULT '',
                full_name     TEXT    DEFAULT '',
                credits       INTEGER DEFAULT 5,
                is_blocked    INTEGER DEFAULT 0,
                total_runs    INTEGER DEFAULT 0,
                joined_at     TEXT    DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS executions (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id       INTEGER NOT NULL,
                filename      TEXT,
                credits_used  INTEGER DEFAULT 0,
                duration_sec  REAL    DEFAULT 0,
                success       INTEGER DEFAULT 1,
                ran_at        TEXT    DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS payment_requests (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id       INTEGER NOT NULL,
                pack_name     TEXT    NOT NULL,
                amount_inr    INTEGER NOT NULL,
                credits       INTEGER NOT NULL,
                txn_id        TEXT    NOT NULL,
                status        TEXT    DEFAULT 'pending',
                created_at    TEXT    DEFAULT (datetime('now'))
            );
        """)
        conn.commit()


# ─────────────────────────────────────────────────────────────────────────────
# Lifespan (startup / shutdown)
# ─────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_tables()
    logger.info("Database tables verified.")
    yield
    logger.info("API shutting down.")


# ─────────────────────────────────────────────────────────────────────────────
# App
# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Code Runner Mini App API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic models
# ─────────────────────────────────────────────────────────────────────────────

class PaymentNotifyRequest(BaseModel):
    user_id: int = Field(..., description="Telegram user ID")
    pack_name: str = Field(..., description="Pack display name (e.g. 'Popular')")
    amount_inr: int = Field(..., description="Amount paid in INR")
    credits: int = Field(..., description="Credits in the pack")
    txn_id: str = Field(..., description="UPI transaction ID provided by user")
    username: str = Field("", description="Telegram username (optional)")
    full_name: str = Field("", description="User display name (optional)")


class GiftRequest(BaseModel):
    sender_id: int = Field(..., description="Sender Telegram user ID")
    receiver_id: int = Field(..., description="Receiver Telegram user ID")
    amount: int = Field(..., ge=1, description="Credits to transfer (must be ≥ 1)")


class ApprovePaymentRequest(BaseModel):
    payment_id: int
    admin_secret: str   # simple shared secret; use proper auth in production


# ─────────────────────────────────────────────────────────────────────────────
# Telegram helper
# ─────────────────────────────────────────────────────────────────────────────

async def send_telegram_message(chat_id: int, text: str) -> bool:
    """Send a Telegram message via Bot API. Returns True on success."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(TELEGRAM_API, json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
            })
            return resp.status_code == 200
    except Exception as exc:
        logger.error(f"Telegram send failed: {exc}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


# ── GET /user/{user_id} ───────────────────────────────────────────────────────

@app.get("/user/{user_id}")
async def get_user(user_id: int):
    """Fetch user stats from the database."""
    user = db_fetchone("SELECT * FROM users WHERE user_id = ?", (user_id,))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Fetch last 5 executions
    recent_runs = db_fetchall(
        """SELECT filename, credits_used, duration_sec, success, ran_at
           FROM executions WHERE user_id = ?
           ORDER BY ran_at DESC LIMIT 5""",
        (user_id,),
    )

    # Determine plan label
    credits = user["credits"]
    if credits >= 1000:
        plan = "👑 Master"
    elif credits >= 400:
        plan = "🔥 Pro"
    elif credits >= 50:
        plan = "🧊 Starter"
    else:
        plan = "🆓 Free"

    return {
        "user_id": user["user_id"],
        "username": user["username"] or "",
        "full_name": user["full_name"] or "User",
        "credits": user["credits"],
        "total_runs": user["total_runs"],
        "is_blocked": bool(user["is_blocked"]),
        "joined_at": user["joined_at"],
        "plan": plan,
        "recent_runs": recent_runs,
    }


# ── POST /notify_payment ───────────────────────────────────────────────────────

@app.post("/notify_payment")
async def notify_payment(req: PaymentNotifyRequest):
    """
    Record a pending payment and notify admin on Telegram.
    Admin must manually verify and use /add_credits in the bot.
    """
    # Persist to payment_requests table
    db_execute(
        """INSERT INTO payment_requests
           (user_id, pack_name, amount_inr, credits, txn_id, status)
           VALUES (?, ?, ?, ?, ?, 'pending')""",
        (req.user_id, req.pack_name, req.amount_inr, req.credits, req.txn_id),
    )

    payment_row = db_fetchone(
        "SELECT id FROM payment_requests WHERE user_id=? AND txn_id=? ORDER BY created_at DESC LIMIT 1",
        (req.user_id, req.txn_id),
    )
    payment_id = payment_row["id"] if payment_row else "?"

    # Compose admin notification
    username_str = f"@{req.username}" if req.username else "N/A"
    admin_msg = (
        "💰 <b>New Payment Request</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 <b>Payment ID:</b> <code>#{payment_id}</code>\n"
        f"👤 <b>User:</b> {req.full_name} ({username_str})\n"
        f"🔢 <b>User ID:</b> <code>{req.user_id}</code>\n"
        f"📦 <b>Pack:</b> {req.pack_name}\n"
        f"💳 <b>Credits:</b> <code>{req.credits}</code>\n"
        f"₹ <b>Amount:</b> <code>₹{req.amount_inr}</code>\n"
        f"🔖 <b>TXN ID:</b> <code>{req.txn_id}</code>\n\n"
        f"✅ To approve, use bot command:\n"
        f"<code>/add_credits {req.user_id} {req.credits}</code>"
    )

    sent = await send_telegram_message(ADMIN_ID, admin_msg)

    # Also notify the user
    user_msg = (
        f"✅ <b>Payment Request Received!</b>\n\n"
        f"📦 Pack: <b>{req.pack_name}</b>\n"
        f"💳 Credits: <code>{req.credits}</code>\n"
        f"₹ Amount: <code>₹{req.amount_inr}</code>\n"
        f"🔖 TXN ID: <code>{req.txn_id}</code>\n\n"
        f"⏳ Your request is under review. Credits will be added within 10 minutes."
    )
    await send_telegram_message(req.user_id, user_msg)

    return {
        "success": True,
        "payment_id": payment_id,
        "admin_notified": sent,
        "message": "Payment request submitted. Credits will be added after verification.",
    }


# ── POST /gift ─────────────────────────────────────────────────────────────────

@app.post("/gift")
async def gift_credits(req: GiftRequest):
    """Transfer credits from sender to receiver."""
    if req.sender_id == req.receiver_id:
        raise HTTPException(status_code=400, detail="Cannot gift credits to yourself.")

    sender = db_fetchone("SELECT * FROM users WHERE user_id = ?", (req.sender_id,))
    if not sender:
        raise HTTPException(status_code=404, detail="Sender not found.")

    receiver = db_fetchone("SELECT * FROM users WHERE user_id = ?", (req.receiver_id,))
    if not receiver:
        raise HTTPException(status_code=404, detail="Receiver user ID not found. Are you sure they have started the bot?")

    if sender["credits"] < req.amount:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient credits. You have {sender['credits']} but tried to gift {req.amount}.",
        )

    if bool(receiver["is_blocked"]):
        raise HTTPException(status_code=403, detail="Cannot gift credits to a blocked user.")

    # Atomic deduct + add
    conn = get_db()
    try:
        conn.execute(
            "UPDATE users SET credits = credits - ? WHERE user_id = ? AND credits >= ?",
            (req.amount, req.sender_id, req.amount),
        )
        conn.execute(
            "UPDATE users SET credits = credits + ? WHERE user_id = ?",
            (req.amount, req.receiver_id),
        )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Transfer failed: {exc}")
    finally:
        conn.close()

    sender_new = db_fetchone("SELECT credits FROM users WHERE user_id = ?", (req.sender_id,))
    receiver_new = db_fetchone("SELECT credits FROM users WHERE user_id = ?", (req.receiver_id,))

    # Notify receiver
    receiver_name = receiver["full_name"] or f"User {req.receiver_id}"
    sender_name = sender["full_name"] or f"User {req.sender_id}"

    await send_telegram_message(
        req.receiver_id,
        f"🎁 <b>You received a gift!</b>\n\n"
        f"<b>{sender_name}</b> gifted you <code>{req.amount}</code> credits!\n"
        f"💳 Your new balance: <code>{receiver_new['credits']}</code>",
    )

    return {
        "success": True,
        "message": f"Successfully gifted {req.amount} credits to {receiver_name}.",
        "sender_new_balance": sender_new["credits"],
        "receiver_new_balance": receiver_new["credits"],
    }


# ── GET /leaderboard ──────────────────────────────────────────────────────────

@app.get("/leaderboard")
async def leaderboard():
    """Top 10 users by credits."""
    rows = db_fetchall(
        """SELECT user_id, username, full_name, credits, total_runs
           FROM users WHERE is_blocked = 0
           ORDER BY credits DESC LIMIT 10""",
    )
    return {"leaderboard": rows}


# ── GET /pending_payments (admin) ─────────────────────────────────────────────

@app.get("/pending_payments")
async def pending_payments(admin_id: int):
    if admin_id != ADMIN_ID:
        raise HTTPException(status_code=403, detail="Admin only.")
    rows = db_fetchall(
        "SELECT * FROM payment_requests WHERE status = 'pending' ORDER BY created_at DESC"
    )
    return {"pending": rows}


# ─────────────────────────────────────────────────────────────────────────────
# Global exception handler
# ─────────────────────────────────────────────────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled error on {request.url}: {exc}")
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": str(exc)},
    )
