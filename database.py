"""
database.py — SQLite persistence layer for Remote Code Runner Bot.

Tables
------
users         : one row per Telegram user
redeem_codes  : generated codes with usage tracking
executions    : audit log of every code-run
"""

import sqlite3
import string
import random
import threading
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple

DB_PATH = "bot_database.db"

# Thread-local connections so each thread gets its own SQLite connection.
_local = threading.local()


def _get_conn() -> sqlite3.Connection:
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA foreign_keys=ON")
    return _local.conn


def _cursor() -> sqlite3.Cursor:
    return _get_conn().cursor()


# ─────────────────────────────────────────────────────────────────────────────
# Schema initialisation
# ─────────────────────────────────────────────────────────────────────────────

def init_db() -> None:
    """Create all tables if they don't exist yet."""
    conn = _get_conn()
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

        CREATE TABLE IF NOT EXISTS redeem_codes (
            code          TEXT    PRIMARY KEY,
            credit_amount INTEGER NOT NULL,
            max_uses      INTEGER NOT NULL,
            used_count    INTEGER DEFAULT 0,
            created_at    TEXT    DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS code_redemptions (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       INTEGER NOT NULL,
            code          TEXT    NOT NULL,
            redeemed_at   TEXT    DEFAULT (datetime('now')),
            UNIQUE(user_id, code)
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
    """)
    conn.commit()


# ─────────────────────────────────────────────────────────────────────────────
# User helpers
# ─────────────────────────────────────────────────────────────────────────────

def upsert_user(user_id: int, username: str, full_name: str) -> None:
    """Insert a new user or update username/full_name if they already exist."""
    conn = _get_conn()
    conn.execute("""
        INSERT INTO users (user_id, username, full_name)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username  = excluded.username,
            full_name = excluded.full_name
    """, (user_id, username or "", full_name or ""))
    conn.commit()


def get_user(user_id: int) -> Optional[Dict[str, Any]]:
    """Return user row as dict, or None if not found."""
    cur = _cursor()
    cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    return dict(row) if row else None


def get_all_users() -> List[Dict[str, Any]]:
    """Return every user row."""
    cur = _cursor()
    cur.execute("SELECT * FROM users ORDER BY joined_at DESC")
    return [dict(r) for r in cur.fetchall()]


def get_unblocked_user_ids() -> List[int]:
    cur = _cursor()
    cur.execute("SELECT user_id FROM users WHERE is_blocked = 0")
    return [r["user_id"] for r in cur.fetchall()]


def get_blocked_users() -> List[Dict[str, Any]]:
    cur = _cursor()
    cur.execute("SELECT * FROM users WHERE is_blocked = 1")
    return [dict(r) for r in cur.fetchall()]


def block_user(user_id: int) -> bool:
    """Block a user. Returns True if a row was updated."""
    conn = _get_conn()
    cur = conn.execute(
        "UPDATE users SET is_blocked = 1 WHERE user_id = ?", (user_id,)
    )
    conn.commit()
    return cur.rowcount > 0


def unblock_user(user_id: int) -> bool:
    """Unblock a user. Returns True if a row was updated."""
    conn = _get_conn()
    cur = conn.execute(
        "UPDATE users SET is_blocked = 0 WHERE user_id = ?", (user_id,)
    )
    conn.commit()
    return cur.rowcount > 0


def is_blocked(user_id: int) -> bool:
    cur = _cursor()
    cur.execute("SELECT is_blocked FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    return bool(row["is_blocked"]) if row else False


# ─────────────────────────────────────────────────────────────────────────────
# Credit helpers
# ─────────────────────────────────────────────────────────────────────────────

def get_credits(user_id: int) -> int:
    cur = _cursor()
    cur.execute("SELECT credits FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    return row["credits"] if row else 0


def add_credits(user_id: int, amount: int) -> int:
    """Add *amount* credits to user; returns new balance."""
    conn = _get_conn()
    conn.execute(
        "UPDATE users SET credits = credits + ? WHERE user_id = ?",
        (amount, user_id)
    )
    conn.commit()
    return get_credits(user_id)


def deduct_credits(user_id: int, amount: int) -> bool:
    """
    Deduct *amount* credits if user has enough.
    Returns True on success, False if insufficient funds.
    """
    conn = _get_conn()
    cur = conn.execute(
        "UPDATE users SET credits = credits - ? WHERE user_id = ? AND credits >= ?",
        (amount, user_id, amount)
    )
    conn.commit()
    return cur.rowcount > 0


def get_total_credits() -> int:
    """Sum of all credits across all users."""
    cur = _cursor()
    cur.execute("SELECT COALESCE(SUM(credits), 0) AS total FROM users")
    return cur.fetchone()["total"]


# ─────────────────────────────────────────────────────────────────────────────
# Redeem code helpers
# ─────────────────────────────────────────────────────────────────────────────

def _random_code(length: int = 12) -> str:
    chars = string.ascii_uppercase + string.digits
    return "".join(random.choices(chars, k=length))


def create_redeem_code(credit_amount: int, max_uses: int) -> str:
    """Generate a unique redeem code and persist it. Returns the code string."""
    conn = _get_conn()
    for _ in range(20):  # retry up to 20 times to avoid collision
        code = _random_code()
        try:
            conn.execute(
                "INSERT INTO redeem_codes (code, credit_amount, max_uses) VALUES (?, ?, ?)",
                (code, credit_amount, max_uses)
            )
            conn.commit()
            return code
        except sqlite3.IntegrityError:
            continue
    raise RuntimeError("Failed to generate a unique redeem code after 20 attempts.")


def delete_redeem_code(code: str) -> bool:
    """Delete a code by its string. Returns True if it existed."""
    conn = _get_conn()
    cur = conn.execute("DELETE FROM redeem_codes WHERE code = ?", (code,))
    conn.commit()
    return cur.rowcount > 0


def redeem_code(user_id: int, code: str) -> Tuple[bool, str, int]:
    """
    Attempt to redeem *code* for *user_id*.

    Returns
    -------
    (success, message, credits_added)
    """
    conn = _get_conn()
    cur = _cursor()

    # Check code exists
    cur.execute("SELECT * FROM redeem_codes WHERE code = ?", (code,))
    row = cur.fetchone()
    if not row:
        return False, "❌ Invalid or expired code.", 0

    # Check usage limit
    if row["used_count"] >= row["max_uses"]:
        return False, "❌ This code has already reached its maximum uses.", 0

    # Check if this user already redeemed it
    cur.execute(
        "SELECT id FROM code_redemptions WHERE user_id = ? AND code = ?",
        (user_id, code)
    )
    if cur.fetchone():
        return False, "❌ You have already redeemed this code.", 0

    credit_amount = row["credit_amount"]

    try:
        # Record redemption
        conn.execute(
            "INSERT INTO code_redemptions (user_id, code) VALUES (?, ?)",
            (user_id, code)
        )
        # Increment usage counter
        conn.execute(
            "UPDATE redeem_codes SET used_count = used_count + 1 WHERE code = ?",
            (code,)
        )
        # Add credits
        conn.execute(
            "UPDATE users SET credits = credits + ? WHERE user_id = ?",
            (credit_amount, user_id)
        )
        conn.commit()
        return True, f"✅ Redeemed! <b>+{credit_amount}</b> credits added.", credit_amount
    except sqlite3.IntegrityError:
        conn.rollback()
        return False, "❌ You have already redeemed this code.", 0


def get_redeem_code_info(code: str) -> Optional[Dict[str, Any]]:
    cur = _cursor()
    cur.execute("SELECT * FROM redeem_codes WHERE code = ?", (code,))
    row = cur.fetchone()
    return dict(row) if row else None


# ─────────────────────────────────────────────────────────────────────────────
# Execution log helpers
# ─────────────────────────────────────────────────────────────────────────────

def log_execution(
    user_id: int,
    filename: str,
    credits_used: int,
    duration_sec: float,
    success: bool = True,
) -> None:
    conn = _get_conn()
    conn.execute(
        """INSERT INTO executions (user_id, filename, credits_used, duration_sec, success)
           VALUES (?, ?, ?, ?, ?)""",
        (user_id, filename, credits_used, duration_sec, int(success))
    )
    conn.execute(
        "UPDATE users SET total_runs = total_runs + 1 WHERE user_id = ?",
        (user_id,)
    )
    conn.commit()


def get_total_executions() -> int:
    cur = _cursor()
    cur.execute("SELECT COALESCE(COUNT(*), 0) AS total FROM executions")
    return cur.fetchone()["total"]


def get_total_users() -> int:
    cur = _cursor()
    cur.execute("SELECT COUNT(*) AS total FROM users")
    return cur.fetchone()["total"]


# ─────────────────────────────────────────────────────────────────────────────
# Active session tracking  (in-memory, not persisted)
# ─────────────────────────────────────────────────────────────────────────────
_active_sessions: Dict[int, Dict[str, Any]] = {}   # user_id -> info dict
_sessions_lock = threading.Lock()


def add_active_session(user_id: int, filename: str, pid: int) -> None:
    with _sessions_lock:
        _active_sessions[user_id] = {
            "filename": filename,
            "pid": pid,
            "started_at": datetime.now().strftime("%H:%M:%S"),
        }


def remove_active_session(user_id: int) -> None:
    with _sessions_lock:
        _active_sessions.pop(user_id, None)


def get_active_sessions() -> List[Dict[str, Any]]:
    with _sessions_lock:
        return [
            {"user_id": uid, **info}
            for uid, info in _active_sessions.items()
        ]
