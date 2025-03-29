import sqlite3
from datetime import datetime, timedelta

class Database:
    def __init__(self, db_name="users.db"):
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self._create_table()

    def _create_table(self):
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE,
            telegram TEXT,
            books TEXT,
            trial_end TEXT,
            payment_due TEXT,
            paid_months INTEGER DEFAULT 0,
            payment_confirmed INTEGER DEFAULT 0
        )''')
        self.conn.commit()

    def add_user(self, email, telegram, books):
        trial_end = (datetime.now() + timedelta(days=3)).strftime('%Y-%m-%d')
        self.cursor.execute(
            "INSERT OR IGNORE INTO users (email, telegram, books, trial_end, payment_due) VALUES (?, ?, ?, ?, ?)",
            (email, telegram, books, trial_end, trial_end)
        )
        self.conn.commit()

    def get_user(self, telegram):
        self.cursor.execute("SELECT * FROM users WHERE telegram = ?", (telegram,))
        return self.cursor.fetchone()

    def update_payment(self, email, months, bonus=0):
        total = months + bonus
        self.cursor.execute(
            "UPDATE users SET paid_months = paid_months + ?, payment_confirmed = 1, payment_due = ? WHERE email = ?",
            (total, (datetime.now() + timedelta(days=30 * total)).strftime('%Y-%m-%d'), email)
        )
        self.conn.commit()

    def get_unpaid_users(self, date):
        self.cursor.execute("SELECT email, telegram FROM users WHERE payment_due = ? AND payment_confirmed = 0", (date,))
        return self.cursor.fetchall()

    def get_users_near_trial_end(self, date):
        self.cursor.execute("SELECT email, telegram FROM users WHERE trial_end = ? AND payment_confirmed = 0", (date,))
        return self.cursor.fetchall()

    def get_all_users(self):
        self.cursor.execute("SELECT email, telegram, trial_end, paid_months, payment_confirmed FROM users")
        return self.cursor.fetchall()
