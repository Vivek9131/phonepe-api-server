from flask import Flask, jsonify, request
import sqlite3
import random
from datetime import datetime, timedelta
import string
import json
import os

app = Flask(__name__)
DATABASE = 'phonepe.db'

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mobile TEXT UNIQUE NOT NULL,
            name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        conn.execute('''
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            balance REAL DEFAULT 0.0,
            upi_id TEXT UNIQUE,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
        ''')

        conn.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            type TEXT CHECK(type IN ('CREDIT', 'DEBIT')),
            merchant TEXT,
            status TEXT CHECK(status IN ('SUCCESS', 'FAILED', 'PENDING')),
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            upi_reference TEXT,
            FOREIGN KEY (account_id) REFERENCES accounts (id)
        )
        ''')

        conn.execute('''
        CREATE TABLE IF NOT EXISTS transaction_payloads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transaction_id INTEGER NOT NULL,
            payload TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (transaction_id) REFERENCES transactions (id)
        )
        ''')

        conn.commit()

# Helper functions
def generate_upi_id(mobile):
    handles = ['@ybl', '@okhdfcbank', '@oksbi', '@okicici']
    return f"{mobile}{random.choice(handles)}"

def get_valid_random_ifsc():
    banks = ['HDFC', 'ICIC', 'SBIN', 'PUNB', 'YESB']
    return random.choice(banks) + '000' + ''.join(random.choices(string.digits, k=3))

def generate_transactions(account_id, count=5):
    merchants = ["Amazon", "Flipkart", "Zomato", "Swiggy", "IRCTC"]
    statuses = ["SUCCESS", "FAILED", "PENDING"]
    
    with get_db() as conn:
        cursor = conn.cursor()
        
        account = conn.execute('SELECT * FROM accounts WHERE id = ?', (account_id,)).fetchone()
        user = conn.execute('SELECT * FROM users WHERE id = ?', (account['user_id'],)).fetchone()
        
        for _ in range(count):
            amount = round(random.uniform(10, 5000), 2)
            txn_type = random.choice(['CREDIT', 'DEBIT'])
            merchant = random.choice(merchants)
            status = random.choice(statuses)
            timestamp = (datetime.now() - timedelta(days=random.randint(0, 30)))
            upi_ref = f"UPI{random.randint(100000000, 999999999)}"
            merchant_id = "MERCHANTUAT" + ''.join(random.choices(string.digits, k=4))
            merchant_txn_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=12))

            # Insert into transactions
            cursor.execute('''
                INSERT INTO transactions 
                (account_id, amount, type, merchant, status, timestamp, upi_reference)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (account_id, amount, txn_type, merchant, status, timestamp.isoformat(), upi_ref))
            txn_id = cursor.lastrowid

            # Create payload JSON
            payload = {
                "merchantId": merchant_id,
                "merchantTransactionId": merchant_txn_id,
                "UserId": user["id"],
                "amount": amount,
                "mobileNumber": user["mobile"],
                "paymentInstrument": {
                    "type": "UPI",
                    "vpa": account["upi_id"],
                    "accountConstraints": [{
                        "accountNumber": ''.join(random.choices(string.digits, k=12)),
                        "ifsc": get_valid_random_ifsc()
                    }]
                },
                "timestamp": timestamp.isoformat()
            }

            # Store JSON payload
            cursor.execute('''
                INSERT INTO transaction_payloads (transaction_id, payload)
                VALUES (?, ?)
            ''', (txn_id, json.dumps(payload)))

            # Update balance
            if txn_type == 'CREDIT':
                cursor.execute('UPDATE accounts SET balance = balance + ? WHERE id = ?', (amount, account_id))
            else:
                cursor.execute('UPDATE accounts SET balance = balance - ? WHERE id = ?', (amount, account_id))
        
        conn.commit()

# API Endpoints
@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    mobile = data.get('mobile')
    name = data.get('name')
    
    if not mobile or len(mobile) != 10 or not mobile.isdigit():
        return jsonify({'error': 'Invalid mobile number'}), 400
    
    try:
        with get_db() as conn:
            # Check if user exists
            user = conn.execute('SELECT * FROM users WHERE mobile = ?', (mobile,)).fetchone()
            if user:
                return jsonify({'error': 'User already exists'}), 400
            
            # Create user
            cursor = conn.cursor()
            cursor.execute('INSERT INTO users (mobile, name) VALUES (?, ?)', (mobile, name))
            user_id = cursor.lastrowid
            
            # Create account
            upi_id = generate_upi_id(mobile)
            cursor.execute('INSERT INTO accounts (user_id, balance, upi_id) VALUES (?, ?, ?)',
                          (user_id, random.uniform(1000, 5000), upi_id))
            account_id = cursor.lastrowid
            
            # Generate transactions
            generate_transactions(account_id, random.randint(5, 10))
            
            return jsonify({
                'message': 'User registered successfully',
                'upi_id': upi_id
            }), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/transactions/<mobile>', methods=['GET'])
def get_transactions(mobile):
    try:
        with get_db() as conn:
            # Get account info
            account = conn.execute('''
                SELECT a.id, a.balance 
                FROM accounts a
                JOIN users u ON a.user_id = u.id
                WHERE u.mobile = ?
            ''', (mobile,)).fetchone()
            
            if not account:
                return jsonify({'error': 'Account not found'}), 404
            
            # Get transactions
            transactions = conn.execute('''
                SELECT * FROM transactions 
                WHERE account_id = ?
                ORDER BY timestamp DESC
                LIMIT 10
            ''', (account['id'],)).fetchall()
            
            # Convert to list of dicts
            transactions_list = [dict(txn) for txn in transactions]
            
            return jsonify({
                'balance': account['balance'],
                'transactions': transactions_list
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/otp/generate', methods=['POST'])
def generate_otp():
    mobile = request.json.get('mobile')
    if not mobile or len(mobile) != 10 or not mobile.isdigit():
        return jsonify({'error': 'Invalid mobile number'}), 400
    
    # In a real app, you would send this OTP via SMS
    otp = ''.join(random.choices(string.digits, k=6))
    return jsonify({'otp': otp})

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)