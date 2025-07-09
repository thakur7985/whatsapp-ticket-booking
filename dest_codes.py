# dest_codes.py
from amadeus_auth import get_access_token
import requests

def get_iata_code(city_name: str):
    token = get_access_token()
    url = "https://test.api.amadeus.com/v1/reference-data/locations"
    headers = {"Authorization": f"Bearer {token}"}
    params = {
        "keyword": city_name,
        "subType": "CITY,AIRPORT"
    }
    response = requests.get(url, headers=headers, params=params)

    try:
        json_data = response.json()
        print("Amadeus API Response:", json_data)  # DEBUG PRINT
        data = json_data.get("data", [])
        if not data:
            return None
        return data[0]["iataCode"]
    except Exception as e:
        print("Error parsing Amadeus response:", e)
        return None
