# amadeus_auth.py
import requests
import os
from dotenv import load_dotenv

load_dotenv()

def get_access_token():
    url = "https://test.api.amadeus.com/v1/security/oauth2/token"
    payload = {
        "grant_type": "client_credentials",
        "client_id": os.getenv("AMADEUS_API_KEY"),
        "client_secret": os.getenv("AMADEUS_API_SECRET")
    }
    response = requests.post(url, data=payload)
    return response.json().get("access_token")
