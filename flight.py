# flight.py
from amadeus_auth import get_access_token
import requests
import os
from dotenv import load_dotenv
from dest_codes import get_iata_code



load_dotenv()

def search_flight_offers(origin_city: str, destination_city: str, date: str):
    origin_code = get_iata_code(origin_city)
    destination_code = get_iata_code(destination_city)

    if not origin_code or not destination_code:
        return {"error": "Invalid city name or no IATA code found."}

    token = get_access_token()
    url = "https://test.api.amadeus.com/v2/shopping/flight-offers"
    headers = {"Authorization": f"Bearer {token}"}

    params = {
        "originLocationCode": origin_code,
        "destinationLocationCode": destination_code,
        "departureDate": date,
        "adults": 1,
        "nonStop": "false",
        "currencyCode": "INR"
    }

    try:
        response = requests.get(url, headers=headers, params=params)
    except requests.exceptions.RequestException as e:
        return {"error": "Request failed", "details": str(e)}

    if response.status_code != 200:
        return {"error": f"API error {response.status_code}", "details": response.text}

    return response.json()
def search_flight_offers(origin_city: str, destination_city: str, date: str):
    origin_code = get_iata_code(origin_city)
    destination_code = get_iata_code(destination_city)

    if not origin_code or not destination_code:
        return []

    token = get_access_token()
    url = "https://test.api.amadeus.com/v2/shopping/flight-offers"
    headers = {"Authorization": f"Bearer {token}"}

    params = {
        "originLocationCode": origin_code,
        "destinationLocationCode": destination_code,
        "departureDate": date,
        "adults": 1,
        "nonStop": "false",
        "currencyCode": "INR"
    }

    try:
        response = requests.get(url, headers=headers, params=params)
    except requests.exceptions.RequestException as e:
        return []

    if response.status_code != 200:
        return []

    # Just return the list of offers
    return response.json().get("data", [])




