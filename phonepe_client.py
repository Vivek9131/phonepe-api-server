import requests

API_BASE_URL = "http://<your-server-ip>:5000/api"  # replace with your actual server IP

def request_mobile():
    mobile = input("Enter your 10-digit mobile number: ").strip()
    if not (mobile.isdigit() and len(mobile) == 10):
        print("Invalid mobile number.")
        return None
    return mobile

def simulate_otp_flow(mobile):
    print(f"Sending OTP to mobile: {mobile}...")
    response = requests.post(f"{API_BASE_URL}/otp/generate", json={"mobile": mobile})
    
    if response.status_code != 200:
        print("Failed to generate OTP:", response.json())
        return False

    otp = response.json().get("otp")
    print(f"[Simulated OTP: {otp}]")  # In production, do NOT show OTP

    user_input_otp = input("Enter OTP: ").strip()
    if user_input_otp == otp:
        print("OTP Verified Successfully!")
        return True
    else:
        print("Incorrect OTP.")
        return False

def fetch_transactions(mobile):
    print(f"\nFetching data for {mobile}...")
    response = requests.get(f"{API_BASE_URL}/transactions/{mobile}")
    
    if response.status_code != 200:
        print("Error:", response.json())
        return
    
    data = response.json()
    print(f"\nBalance: ₹{data['balance']:.2f}")
    print("\nRecent Transactions:")
    for txn in data["transactions"]:
        print(f"- {txn['timestamp'][:19]} | ₹{txn['amount']} | {txn['type']} | {txn['merchant']} | {txn['status']}")

def main():
    mobile = request_mobile()
    if not mobile:
        return

    if simulate_otp_flow(mobile):
        fetch_transactions(mobile)

if __name__ == "__main__":
    main()
