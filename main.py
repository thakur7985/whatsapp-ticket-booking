import os
import uuid
import traceback
import razorpay
import logging
from fpdf import FPDF
import mysql.connector
from pydantic import BaseModel
from twilio.rest import Client
from dotenv import load_dotenv
from databases import Database
from flight import search_flight_offers
from dest_codes import get_iata_code 
from fastapi.concurrency import run_in_threadpool
from datetime import datetime, timedelta
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware


# ======= Setup logging ==============
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ======= Load environment variables ==========
load_dotenv()
app = FastAPI()
user_sessions = {}
user_last_interaction = {}  


# ========= Database integration ==============
DB_USER = "root"
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = "localhost"
DB_NAME = os.getenv("DB_NAME")

if not DB_PASSWORD or not DB_NAME:
    logger.error("Database password or name environment variables are not set.")
    raise RuntimeError("Database password or name environment variables are not set.")

DATABASE_URL = f"mysql+asyncmy://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/{DB_NAME}"
database = Database(DATABASE_URL)


# ====== Twilio Integration ========== 
account_sid = os.getenv("TWILIO_ACCOUNT_SID")
auth_token = os.getenv("TWILIO_AUTH_TOKEN")
if not account_sid or not auth_token:
    logger.warning("Twilio account SID or auth token not set in environment variables.")
try:
    client = Client(account_sid, auth_token)
except Exception as e:
    logger.error(f"Error initializing Twilio Client: {e}")
    client = None


# ====== Razorpay payment integration ==============
RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")
if not RAZORPAY_KEY_ID or not RAZORPAY_KEY_SECRET:
    logger.warning("Razorpay key id or secret not set in environment variables.")
try:
    razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
except Exception as e:
    logger.error(f"Error initializing Razorpay Client: {e}")
    razorpay_client = None


# ======= Allow CORS (optional) ===============
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_methods=["*"],
    allow_headers=["*"],
)

class MessageRequest(BaseModel):
    recipient_number: str
    message_body: str

def is_valid_departure_date(date_str: str) -> bool:
    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
        today = datetime.today().date()
        return today <= date_obj <= today + timedelta(days=10) 
    except ValueError:
        return False

# =============== Datbase tables ==============
@app.on_event("startup")
async def startup():
    try:
        await database.connect()

        await database.execute("""
            CREATE TABLE IF NOT EXISTS users (
                Sno INT AUTO_INCREMENT PRIMARY KEY,
                Pid VARCHAR(50) NOT NULL,
                whatsapp_id VARCHAR(100) UNIQUE NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        await database.execute("""
            CREATE TABLE IF NOT EXISTS flight_bookings (
                Sno INT AUTO_INCREMENT PRIMARY KEY,
                Pid VARCHAR(50) NOT NULL UNIQUE,
                whatsapp_id VARCHAR(100) NOT NULL,
                origin VARCHAR(100),
                destination VARCHAR(100),
                departure_time VARCHAR(100),
                arrival_time VARCHAR(100),
                price DECIMAL(10, 2),
                airline_name VARCHAR(255),
                total_passengers INT,
                booking_reference VARCHAR(100) UNIQUE,
                razorpay_order_id VARCHAR(100),
                booking_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        await database.execute("""
            CREATE TABLE IF NOT EXISTS passengers (
                Psrid VARCHAR(50) PRIMARY KEY,
                Pid VARCHAR(50) NOT NULL,
                p_name VARCHAR(100) NOT NULL,
                dob DATE NOT NULL,
                gender VARCHAR(10) NOT NULL,
                seat VARCHAR(10),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (Pid) REFERENCES flight_bookings(Pid)
            );
        """)
        logger.info("Database connected.")
    except Exception as e:
        logger.error(f"Error during startup database setup: {e}")
        raise


@app.on_event("shutdown")
async def shutdown():
    try:
        await database.disconnect()
        logger.info("Database disconnected.")
    except Exception as e:
        logger.error(f"Error during database disconnect: {e}")

@app.get("/")
def home():
    return {"status": "Server is running"}


# ============ Booked ticket history ===============
async def send_booking_history(user_id: str):
    bookings = await database.fetch_all("""
        SELECT booking_reference, origin, destination, departure_time, arrival_time, total_passengers, price
        FROM flight_bookings
        WHERE whatsapp_id = :user_id
        ORDER BY booking_time DESC
        LIMIT 5
    """, values={"user_id": user_id})

    if not bookings:
        return PlainTextResponse("❌ No bookings found for your number.")

    reply = "🧾 *Your Recent Bookings:*\n\n"
    for idx, b in enumerate(bookings, start=1):
        reply += (
            f"{idx}. Ref: *{b['booking_reference']}*\n"
            f"   ✈️ {b['origin']} → {b['destination']}\n"
            f"   🕒 {b['departure_time']} → {b['arrival_time']}\n"
            f"   👥 Passengers: {b['total_passengers']}\n"
            f"   💰 Price: ₹{b['price']}\n\n"
        )
    reply += "Reply *hi* to start a new booking."

    return PlainTextResponse(reply)


# ========== sending whatsapp msg =============
@app.post("/send-whatsapp/")
def send_whatsapp(request: MessageRequest):
    if client is None:
        logger.error("Twilio client is not initialized.")
        return JSONResponse(content={"error": "Twilio client not configured"}, status_code=500)

    try:
        message = client.messages.create(
            body=request.message_body,
            from_='whatsapp:+14155238886',
            to=f'whatsapp:{request.recipient_number}'
        )
        logger.info(f"WhatsApp message sent to {request.recipient_number}, SID: {message.sid}")
        return {"status": "sent successfully", "message_sid": message.sid}
    except Exception as e:
        logger.error(f"Error sending WhatsApp message: {str(e)}")
        return JSONResponse(content={"error": "Failed to send message. Please check the recipient number and try again."}, status_code=400)

def check_payment_status(order_id):
    if razorpay_client is None:
        logger.error("Razorpay client is not initialized.")
        return False

    try:
        payments = razorpay_client.order.payments(order_id)["items"]
        for payment in payments:
            if payment["status"] == "captured":
                return True
    except Exception as e:
        logger.error(f"Error checking payment status for order {order_id}: {e}")
    return False


# ============ PDF Generate ==============
def generate_ticket_pdf(booking_reference: str, flight_details: dict, passengers: list):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)

    pdf.cell(200, 10, txt="Flight Ticket", ln=True, align='C')
    pdf.cell(200, 10, txt=f"Booking Reference: {booking_reference}", ln=True)
    pdf.cell(200, 10, txt=f"Origin: {flight_details['origin']}", ln=True)
    pdf.cell(200, 10, txt=f"Destination: {flight_details['destination']}", ln=True)
    pdf.cell(200, 10, txt=f"Departure Time: {flight_details['departure_time']}", ln=True)
    pdf.cell(200, 10, txt=f"Arrival Time: {flight_details['arrival_time']}", ln=True)
    pdf.cell(200, 10, txt=f"Airline: {flight_details['airline']}", ln=True)
    pdf.cell(200, 10, txt=f"Total Passengers: {len(passengers)}", ln=True)

    pdf.cell(200, 10, txt="Passenger Details:", ln=True)
    for passenger in passengers:
        pdf.cell(200, 10, txt=f"Name: {passenger['name']}, Age: {passenger['age']}, Gender: {passenger['gender']}, Seat: {passenger['seat']}", ln=True)

    pdf_file_path = f"{booking_reference}.pdf"
    pdf.output(pdf_file_path)
    return pdf_file_path

@app.post("/webhook")
async def whatsapp_webhook(request: Request):
    form = await request.form()
    raw_input = form.get("Body", "").strip()
    user_input = raw_input.title() 
    user_id = form.get("From")


    # =============== Check for duplicate messages ===========
    current_time = datetime.utcnow()
    last_interaction_time = user_last_interaction.get(user_id, current_time - timedelta(seconds=5))
    
    if (current_time - last_interaction_time).total_seconds() < 2:  
        return PlainTextResponse("Please wait a moment before sending another message.")

    user_last_interaction[user_id] = current_time  
    

    # =========== Reset session if user types greetings or start commands ==============
    if user_input in ["Hi", "Hello", "Start"]:
        user_sessions[user_id] = {
            "step": "ask_origin",
            "origin": "",
            "destination": "",
            "date": "",
            "flights": [],
            "selected_flight": {},
            "passengers": [],
            "current_passenger": {},
            "payment_confirmed": False,
            "last_interaction": current_time
        }
        return PlainTextResponse(
            "Welcome to ✈️ FlightBot!\n\nPlease enter the *departure city name* (e.g., New Delhi):"
        )

    session = user_sessions.get(user_id)
   
    if not session or (current_time - session.get("last_interaction", current_time)) > timedelta(hours=1):
        user_sessions[user_id] = {
            "step": "ask_origin",
            "origin": "",
            "destination": "",
            "date": "",
            "flights": [],
            "selected_flight": {},
            "passengers": [],
            "current_passenger": {},
            "payment_confirmed": False,
            "last_interaction": current_time
        }
        session = user_sessions[user_id]
        return PlainTextResponse(
            "Session started.\n\nPlease enter the *departure city name* (e.g., New Delhi):"
        )

    session["last_interaction"] = current_time

    try:
        step = session["step"]

        if step == "ask_origin":
            session["origin"] = user_input 
            session["step"] = "ask_destination"
            user_sessions[user_id] = session
            return PlainTextResponse("Great! Now enter the *destination city name* (e.g., Mumbai):")

        elif step == "ask_destination":
            session["destination"] = user_input 
            session["step"] = "ask_date"
            user_sessions[user_id] = session
            return PlainTextResponse("Awesome! Please enter the *departure date* in YYYY-MM-DD format:")

        elif step == "ask_date":
            if not is_valid_departure_date(user_input):
                today = datetime.today().date()
                allowed_dates = "\n".join(
                    f"✅ {(today + timedelta(days=i)).strftime('%Y-%m-%d')}" for i in range(11)  # Allow up to 10 days
                )
                return PlainTextResponse(
                    "❌ Invalid date.\n\nYou can only book flights from *today* to *10 days from today*.\nValid dates:\n" + allowed_dates
                )
            session["date"] = user_input
          
            origin_iata = await run_in_threadpool(get_iata_code, session["origin"])
            destination_iata = await run_in_threadpool(get_iata_code, session["destination"])
            if not origin_iata or not destination_iata:
                return PlainTextResponse("❌ Invalid city names. Please check and try again.")

            offers = await run_in_threadpool(search_flight_offers, origin_iata, destination_iata, session["date"])
            if not offers:
                return PlainTextResponse("No flights found. Try a different date or route.")
            session["flights"] = offers[:5]
            session["step"] = "select_flight"
            user_sessions[user_id] = session

            reply = "✈️ Available Flights:\n\n"
            for idx, flight in enumerate(session["flights"], start=1):
                segment = flight["itineraries"][0]["segments"][0]
                airline = flight["validatingAirlineCodes"][0]
                price = flight["price"]["total"]
                reply += (
                    f"{idx}. {segment['departure']['iataCode']} ({segment['departure']['at']}) ➡️ "
                    f"{segment['arrival']['iataCode']} ({segment['arrival']['at']})\n"
                    f"   Airline: {airline}, Price: ₹{price}\n\n"
                )
            reply += "Please reply with the flight number (1–5) to confirm your choice."
            return PlainTextResponse(reply)

        elif step == "select_flight":
            try:
                choice = int(user_input) - 1
                if choice not in range(len(session["flights"])):
                    raise ValueError
                session["selected_flight"] = session["flights"][choice]
                session["step"] = "ask_name"
                user_sessions[user_id] = session
                return PlainTextResponse("Please enter the *name* of passenger 1:")
            except (IndexError, ValueError):
                return PlainTextResponse("Invalid choice. Please reply with a number between 1 and 5.")

        elif step == "ask_name":
            session["current_passenger"] = {"name": raw_input.title()}
            session["step"] = "ask_age"
            user_sessions[user_id] = session
            return PlainTextResponse("Enter their *age*:")

        elif step == "ask_age":
            if not user_input.isdigit() or int(user_input) <= 0:
                return PlainTextResponse("Please enter a valid age.")
            session["current_passenger"]["age"] = int(user_input)
            session["step"] = "ask_gender"
            user_sessions[user_id] = session
            return PlainTextResponse("Enter their *gender* (Male/Female/Other):")

        elif step == "ask_gender":
            gender = raw_input.capitalize()
            if gender not in ["Male", "Female", "Other"]:
                return PlainTextResponse("Please enter a valid gender.")
            session["current_passenger"]["gender"] = gender
            session["step"] = "ask_seat"
            user_sessions[user_id] = session
            return PlainTextResponse("Enter their *preferred seat* (e.g., 12A):")

        elif step == "ask_seat":
            session["current_passenger"]["seat"] = user_input.upper()
            session["passengers"].append(session["current_passenger"])
            passenger_count = len(session["passengers"])

            if passenger_count < 6:
                session["step"] = "add_another_passenger"
                user_sessions[user_id] = session
                return PlainTextResponse(f"Passenger {passenger_count} added ✅\nDo you want to add another passenger? (yes/no)")
            else:
                session["step"] = "confirm_booking"
                user_sessions[user_id] = session
                return PlainTextResponse("Max 6 passengers reached. Ready to confirm your booking. Reply *confirm* to proceed.")

        elif step == "add_another_passenger":
            if user_input.lower() == "yes":
                session["step"] = "ask_name"
                user_sessions[user_id] = session
                return PlainTextResponse(f"Please enter the *name* of passenger {len(session['passengers']) + 1}:")
            elif user_input.lower() == "no":
                session["step"] = "confirm_booking"
                user_sessions[user_id] = session
                return PlainTextResponse("Booking details completed. Reply *confirm* to proceed to payment.")
            else:
                return PlainTextResponse("Please reply with *yes* or *no*.")

        elif step == "confirm_booking":
            if user_input.lower() == "confirm":
                flight = session["selected_flight"]
                segment = flight["itineraries"][0]["segments"][0]
                origin = segment["departure"]["iataCode"]
                destination = segment["arrival"]["iataCode"]
                departure_time = segment["departure"]["at"]
                arrival_time = segment["arrival"]["at"]
                price = float(flight["price"]["total"])
                airline = flight["validatingAirlineCodes"][0]
                booking_reference = f"FL-{datetime.now().strftime('%Y%m%d%H%M%S')}"
                pid = str(uuid.uuid4())
                total_passengers = len(session["passengers"])

                if razorpay_client is None:
                    logger.error("Razorpay client not configured.")
                    return PlainTextResponse("Payment system unavailable. Please try again later.")

                amount_paise = int(price * 100) 
                try:
                    payment_link_response = razorpay_client.payment_link.create({
                        "amount": amount_paise,
                        "currency": "INR",
                        "accept_partial": False,
                        "description": f"Flight booking {booking_reference}",
                        "customer": {
                            "name": session["passengers"][0]["name"],
                            "contact": user_id.replace("whatsapp:", ""),
                        },
                        "notify": {
                            "sms": True,
                            "email": False
                        },
                        "reminder_enable": True,
                        "callback_url": "https://example.com/payment/callback",  # Update this to your actual callback URL
                        "callback_method": "get"
                    })
                except Exception as e:
                    logger.error(f"Error creating payment link: {e}")
                    return PlainTextResponse("Failed to create payment link. Please try again later.")

                if "id" not in payment_link_response or "short_url" not in payment_link_response:
                    logger.error(f"Invalid payment link response: {payment_link_response}")
                    return PlainTextResponse("Failed to create payment link. Please try again later.")

                payment_link_url = payment_link_response["short_url"]

                await database.execute("""
                    INSERT INTO flight_bookings (
                        Pid, whatsapp_id, origin, destination, departure_time, arrival_time,
                        price, airline_name, total_passengers, booking_reference, razorpay_order_id
                    ) VALUES (
                        :Pid, :whatsapp_id, :origin, :destination, :departure_time, :arrival_time,
                        :price, :airline_name, :total_passengers, :booking_reference, :razorpay_order_id
                    )
                """, {
                    "Pid": pid,
                    "whatsapp_id": user_id,
                    "origin": origin,
                    "destination": destination,
                    "departure_time": departure_time,
                    "arrival_time": arrival_time,
                    "price": price,
                    "airline_name": airline,
                    "total_passengers": total_passengers,
                    "booking_reference": booking_reference,
                    "razorpay_order_id": payment_link_response['id']
                })

                def calculate_dob(age: int):
                    today = datetime.today()
                    birth_year = today.year - age
                    return datetime(birth_year, today.month, today.day).date()

                for p in session["passengers"]:
                    dob = calculate_dob(p["age"])
                    await database.execute("""
                        INSERT INTO passengers (
                            Psrid, Pid, p_name, dob, gender, seat
                        ) VALUES (
                            :Psrid, :Pid, :p_name, :dob, :gender, :seat
                        )
                    """, {
                        "Psrid": str(uuid.uuid4()),
                        "Pid": pid,
                        "p_name": p["name"],
                        "dob": dob,
                        "gender": p["gender"],
                        "seat": p["seat"]
                    })

                session["step"] = "awaiting_payment"
                session["razorpay_order_id"] = payment_link_response['id']
                user_sessions[user_id] = session

                return PlainTextResponse(
                    f"🎉 Booking Created!\n\n"
                    f"📌 Ref: *{booking_reference}*\n"
                    f"{origin} → {destination}\n"
                    f"Departure: {departure_time}\n"
                    f"Arrival: {arrival_time}\n"
                    f"Airline: {airline}\n"
                    f"Total Passengers: {total_passengers}\n\n"
                    f"💰 Price: ₹{price}\n"
                    f"Please complete your payment using the following link:\n{payment_link_url}\n\n"
                    f"After payment, reply with *paid* to confirm your booking."
                )
            else:
                return PlainTextResponse("Please reply with *confirm* to proceed to payment.")

        elif step == "awaiting_payment":
            
            #  =========== payment confirmation keywords =============
            if user_input.lower() in ["paid", "payment done", "done"]:
                razorpay_order_id = session.get("razorpay_order_id")
                if not razorpay_order_id:
                    return PlainTextResponse("Payment info missing. Please contact support.")

                if check_payment_status(razorpay_order_id):
                    session["payment_confirmed"] = True
                    session["step"] = "booking_confirmed"
                    user_sessions[user_id] = session

                    # =========== Generate ticket PDF ===========
                    pdf_file_path = generate_ticket_pdf(booking_reference, session["selected_flight"], session["passengers"])

                    return PlainTextResponse(
                        "✅ Payment confirmed.\n"
                        "Your ticket booking is successful! 🎉\n"
                        "Thank you for booking with FlightBot.\n"
                        "Have a pleasant journey! ✈️\n"
                        f"You can download your ticket here: {pdf_file_path}"
                    )
                else:
                    return PlainTextResponse(
                        "⚠️ Payment not detected yet. Please make sure you completed the payment.\n"
                        "If you have paid, wait a moment and reply *paid* again."
                    )
            else:
                return PlainTextResponse(
                    "Waiting for payment confirmation.\n"
                    "Please reply with *paid* once you complete the payment."
                )

        elif step == "booking_confirmed":
            return PlainTextResponse(
                "Your booking is already confirmed.\n"
                "For new booking, reply *hi* or *start*."
            )

        else:
            
            user_sessions.pop(user_id, None)
            return PlainTextResponse(
                "Something went wrong. Session reset.\n"
                "Please reply *hi* to start again."
            )

    except Exception as e:
        logger.error(f"Exception in webhook processing: {traceback.format_exc()}")
        
        user_sessions.pop(user_id, None)
        return PlainTextResponse("An error occurred. Please try again later. Reply *hi* to start again.")
