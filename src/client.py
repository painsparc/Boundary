import json
import os

import requests

API_URL = os.environ.get("BOUNDARY_URL", "http://127.0.0.1:8000")


def run_client():
    payload = {
        "data": {
            "name": "Test User",
            "age": 43,
            "city": "Pune",
            "occupation": "Systems Architect",
            "free_text_note": "Requesting medical reimbursement for recent cardiology appointment.",
            "transaction_id": "TXN-9988",
        },
        "destination": "third_party_llm",
        "purpose": "customer_support",
    }
    print("Sending Request to Boundary API...")
    try:
        response = requests.post(f"{API_URL}/protect", json=payload, timeout=30)
        if not response.ok:
            print(f"API returned {response.status_code}: {response.text}")
            return
        print("Success! Processed payload:\n")
        print(json.dumps(response.json(), indent=2))
    except requests.RequestException as e:
        print(f"API Request Failed: {e}")


if __name__ == "__main__":
    run_client()
