import requests
import json
import uuid

# Base URL of the hosted ADK playground
BASE_URL = "http://127.0.0.1:18081"
RUN_ENDPOINT = f"{BASE_URL}/run"

# Generate a unique session ID for this interaction
session_id = f"demo-session-{uuid.uuid4().hex[:8]}"
user_id = "demo-user"

print("=" * 80)
print(f"Starting test run with Session ID: {session_id}")
print("=" * 80)

# Create session first (since auto_create_session is False on the server by default)
print(f"\n--- Creating session '{session_id}' for app 'app' ---")
session_url = f"{BASE_URL}/apps/app/users/{user_id}/sessions"
create_res = requests.post(session_url, json={"sessionId": session_id})
create_res.raise_for_status()
print(f"Session created successfully: {create_res.json()}")

# Sample document/form content to analyze
sample_content = (
    "The government healthcare enrollment form requires patients to provide their "
    "name, address, and a unique identification number. The form contains 3 "
    "sections: Personal Information, Medical History, and Insurance Details. "
    "Complex fields include 'aforementioned conditions' and 'antecedent "
    "diagnoses'. The form uses gray text on white background."
)

print("\n--- STEP 1: Sending accessibility analysis request ---")
print(f"Content sent:\n{sample_content}\n")

payload = {
    "userId": user_id,
    "sessionId": session_id,
    "newMessage": {
        "role": "user",
        "parts": [
            {
                "text": sample_content
            }
        ]
    }
}

try:
    response = requests.post(RUN_ENDPOINT, json=payload)
    response.raise_for_status()
    events = response.json()
    
    # Locate and print the output from the final node or HITL node in this turn
    hitl_prompt = ""
    for event in events:
        content = event.get("content")
        if content and content.get("parts"):
            for part in content["parts"]:
                text = part.get("text")
                if text:
                    print(text)
                    if "✋ Human Verification Required" in text:
                        hitl_prompt = text
except Exception as e:
    print(f"Error during Step 1: {e}")
    exit(1)


print("\n" + "=" * 80)
print("--- STEP 2: Approving the report (HITL) ---")
print("Sending 'approve' command to finalize output...\n")

approve_payload = {
    "userId": user_id,
    "sessionId": session_id,
    "newMessage": {
        "role": "user",
        "parts": [
            {
                "text": "approve"
            }
        ]
    }
}

try:
    response = requests.post(RUN_ENDPOINT, json=approve_payload)
    response.raise_for_status()
    events = response.json()
    
    # Locate and print the final output
    for event in events:
        content = event.get("content")
        if content and content.get("parts"):
            for part in content["parts"]:
                text = part.get("text")
                if text:
                    print(text)
except Exception as e:
    print(f"Error during Step 2: {e}")
    exit(1)

print("\n" + "=" * 80)
print("Test completed successfully.")
print("=" * 80)
