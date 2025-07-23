from flask import Flask, request, jsonify
from datetime import datetime, timedelta
import random, string, json, sqlite3, os
import requests
from uuid import uuid4

app = Flask(__name__)
DB_PATH = "phonepe.db"
OTP_STORE = {}

# ---------- DB INITIALIZATION ----------
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        
        # Enable foreign key constraints
        cursor.execute("PRAGMA foreign_keys = ON")
        
        # Create tables with IF NOT EXISTS to prevent errors
        tables = [
            '''CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mobile TEXT UNIQUE NOT NULL
            )''',
            '''CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                upi_id TEXT,
                balance REAL DEFAULT 0,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )''',
            '''CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                type TEXT NOT NULL,
                merchant TEXT,
                status TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                upi_reference TEXT,
                FOREIGN KEY(account_id) REFERENCES accounts(id)
            )''',
            '''CREATE TABLE IF NOT EXISTS transaction_payloads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transaction_id INTEGER NOT NULL,
                payload TEXT NOT NULL,
                FOREIGN KEY(transaction_id) REFERENCES transactions(id)
            )''',
            '''CREATE TABLE IF NOT EXISTS generation_counts (
                mobile TEXT PRIMARY KEY,
                count INTEGER DEFAULT 0,
                last_generated TIMESTAMP
            )'''
        ]
        
        for table in tables:
            cursor.execute(table)
        
        conn.commit()
        print("✅ Database initialized and tables verified.")

# ---------- DB UTILITY ----------
def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn

# ---------- RANDOM DATA HELPERS ----------
def get_valid_random_ifsc():
    bank_codes = ["HDFC", "ICIC", "SBIN", "AXIS", "KKBK", "YESB"]
    for _ in range(10):
        bank_code = random.choice(bank_codes)
        number = ''.join(random.choices(string.digits, k=7))
        ifsc = f"{bank_code}{number}"
        try:
            response = requests.get(f"https://ifsc.razorpay.com/{ifsc}")
            if response.status_code == 200:
                return ifsc
        except:
            continue
    return "HDFC0000123"


def generate_dynamic_transactions(account_id, mobile=None, user_id=None):
    with get_db() as conn:
        cursor = conn.cursor()

        # -- Step 1: Handle generation count --
        cursor.execute("SELECT count FROM generation_counts WHERE mobile = ?", (mobile,))
        row = cursor.fetchone()
        count = row["count"] if row else 0

        if count >= 3:
            # Delete old transactions and payloads
            cursor.execute("SELECT id FROM transactions WHERE account_id = ?", (account_id,))
            txn_ids = [row["id"] for row in cursor.fetchall()]
            if txn_ids:
                cursor.executemany("DELETE FROM transaction_payloads WHERE transaction_id = ?", [(i,) for i in txn_ids])
                cursor.execute("DELETE FROM transactions WHERE account_id = ?", (account_id,))
            count = 0  # Reset count

        # -- Step 2: Proceed with generation --
        upi_handles = ["@ybl", "@okhdfcbank", "@oksbi", "@okicici", "@okaxis", "@paytm", "@upi"]
        balance = 0

        for _ in range(random.randint(5, 10)):
            amount = round(random.uniform(100, 5000), 2)
            txn_type = random.choice(["CREDIT", "DEBIT"])
            status = random.choice(["SUCCESS", "FAILED", "PENDING"])
            timestamp = datetime.now() - timedelta(days=random.randint(0, 30))
            merchant_id = uuid4().hex[:20].upper()
            merchant_txn_id = uuid4().hex[:25].upper()
            vpa = f"{mobile}{random.choice(upi_handles)}"

            cursor.execute('''
                INSERT INTO transactions 
                (account_id, amount, type, merchant, status, timestamp, upi_reference)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                account_id, amount, txn_type, merchant_id, status, timestamp.isoformat(),
                f"UPI{random.randint(100000000, 999999999)}"
            ))
            txn_id = cursor.lastrowid

            payload = {
                "merchantId": merchant_id,
                "merchantTransactionId": merchant_txn_id,
                "UserId": uuid4().hex[:15].upper(),
                "amount": amount,
                "mobileNumber": mobile,
                "paymentInstrument": {
                    "type": "UPI",
                    "vpa": vpa,
                    "accountConstraints": [{
                        "accountNumber": ''.join(random.choices(string.digits, k=12)),
                        "ifsc": get_valid_random_ifsc()
                    }]
                },
                "timestamp": timestamp.isoformat()
            }

            cursor.execute(
                "INSERT INTO transaction_payloads (transaction_id, payload) VALUES (?, ?)",
                (txn_id, json.dumps(payload))
            )

            if txn_type == "CREDIT":
                balance = random.randint(10000, 100000) + abs(amount)
            elif txn_type == "DEBIT":
                balance = max(1000, random.randint(10000, 100000) - abs(amount))

        # Update final balance
        cursor.execute("UPDATE accounts SET balance = ? WHERE id = ?", (max(balance, 0), account_id))

        # -- Step 3: Update generation count --
        if row:
            cursor.execute("UPDATE generation_counts SET count = ? WHERE mobile = ?", (count + 1, mobile))
        else:
            cursor.execute("INSERT INTO generation_counts (mobile, count) VALUES (?, ?)", (mobile, 1))

        conn.commit()

def generate_indian_mobile():
    """Generates a random valid Indian mobile number"""
    prefixes = ['6', '7', '8', '9']
    return random.choice(prefixes) + ''.join(random.choices(string.digits, k=9))

# ---------- ROUTES ----------
@app.route("/api/otp/generate", methods=["POST"])
def generate_otp():
    data = request.get_json()
    mobile = data.get("mobile")
    if not mobile:
        return jsonify({"error": "Missing mobile"}), 400

    otp = str(random.randint(1000, 9999))
    OTP_STORE[mobile] = otp

    with get_db() as conn:
        cursor = conn.cursor()
        user = cursor.execute("SELECT * FROM users WHERE mobile = ?", (mobile,)).fetchone()
        if not user:
            cursor.execute("INSERT INTO users (mobile) VALUES (?)", (mobile,))
            user_id = cursor.lastrowid
            upi_id = f"{mobile}@upi"
            cursor.execute("INSERT INTO accounts (user_id, upi_id, balance) VALUES (?, ?, ?)", (user_id, upi_id, 0.0))
            account_id = cursor.lastrowid
            conn.commit()

            # Generate dynamic transactions for the new user
            generate_dynamic_transactions(account_id, mobile, user_id)

    return jsonify({"message": "OTP sent", "otp": otp})

@app.route("/api/transactions/<mobile>", methods=["GET"])
def get_transactions(mobile):
    try:
        # Validate Indian mobile number format
        if not (mobile.isdigit() and len(mobile) == 10 and mobile.startswith(('6', '7', '8', '9'))):
            return jsonify({'error': 'Invalid Indian mobile number'}), 400

        with get_db() as conn:
            cursor = conn.cursor()
            
            # Fetch user
            user = cursor.execute("SELECT * FROM users WHERE mobile = ?", (mobile,)).fetchone()
            
            if not user:
                # Create new user
                cursor.execute("INSERT INTO users (mobile) VALUES (?)", (mobile,))
                user_id = cursor.lastrowid
                upi_id = f"{mobile}@ybl"
                cursor.execute("INSERT INTO accounts (user_id, upi_id, balance) VALUES (?, ?, ?)", 
                               (user_id, upi_id, 0.0))
                account_id = cursor.lastrowid

                # Set generation count = 1 (this is first call)
                cursor.execute("INSERT INTO generation_counts (mobile, count) VALUES (?, 1)", (mobile,))
                
                # Generate initial transactions
                generate_dynamic_transactions(account_id, mobile, user_id)
                conn.commit()
            else:
                user_id = user["id"]

                # Get account
                account = cursor.execute("SELECT * FROM accounts WHERE user_id = ?", (user_id,)).fetchone()
                if not account:
                    return jsonify({"error": "Account not found"}), 404

                account_id = account["id"]

                # Get generation count
                count_row = cursor.execute("SELECT count FROM generation_counts WHERE mobile = ?", (mobile,)).fetchone()
                current_count = count_row["count"] if count_row else 0

                if current_count >= 3:
                    # Clear old transactions
                    cursor.execute("DELETE FROM transactions WHERE account_id = ?", (account_id,))
                    
                    # Generate new transactions
                    generate_dynamic_transactions(account_id, mobile, user_id)

                    # Reset count to 1 (this is the new cycle)
                    cursor.execute("UPDATE generation_counts SET count = 1 WHERE mobile = ?", (mobile,))
                else:
                    # Increment count
                    cursor.execute("UPDATE generation_counts SET count = count + 1 WHERE mobile = ?", (mobile,))
                
                conn.commit()

            # Fetch account again to get updated balance
            account = cursor.execute("SELECT * FROM accounts WHERE user_id = ?", (user_id,)).fetchone()

            # Fetch latest 10 transactions
            txns = cursor.execute('''
                SELECT tp.payload
                FROM transactions t
                JOIN transaction_payloads tp ON tp.transaction_id = t.id
                WHERE t.account_id = ?
                ORDER BY t.timestamp DESC
                LIMIT 10
            ''', (account_id,)).fetchall()

            return jsonify({
                "mobile": mobile,
                "balance": account["balance"],
                "transactions": [json.loads(txn["payload"]) for txn in txns],
            })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

    
# ---------- APP ENTRY ----------
if __name__ == "__main__":
    init_db()
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))