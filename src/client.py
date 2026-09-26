import requests
import json

def run_client():
    payload = {
        "data": {
            "name": "Pushkar Wagh",
            "age": 18,
            "city": "Pune",
            "occupation": "Systems Architect",
            "free_text_note": "Requesting medical reimbursement for recent cardiology appointment.",
            "transaction_id": "TXN-9988"
        },
        "destination": "third_party_llm",
        "purpose": "customer_support"
    }

    print("Sending Request to Boundary API...")
    try:
        response = requests.post("http://127.0.0.1:8000/protect", json=payload)
        response.raise_for_status()
        print("Success! Processed payload:\n")
        print(json.dumps(response.json(), indent=2))
    except Exception as e:
        print(f"API Request Failed: {e}")

if __name__ == "__main__":
    run_client()