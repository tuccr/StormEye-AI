import requests

API_URL = "http://127.0.0.1:8000"

def retrieve_video_feed(message: str) -> str:
    response = requests.post(f"{API_URL}/process", json={"message": message})
    if response.ok:
        return response.json().get("received", "No response")
    return f"Error: {response.status_code}"

