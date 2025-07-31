#  WhatsApp Ticket Booking Bot

An AI-powered WhatsApp chatbot for booking bus and flight tickets using FastAPI, Twilio, Rasa, and MySQL — integrated with payment gateway, PDF ticket generation, and smart conversational flows.

WhatsApp Chatbot with natural flow
✅ Book Bus or Flight tickets with step-by-step flow
✅ Integrated with Razorpay for secure payments
✅ PDF Ticket Generator with passenger & trip details
✅ Multi-passenger support
✅ Booking confirmation, history, and rebooking options
✅ Built with FastAPI, Twilio API, MySQL, Rasa, and HTML Form integration
✅ Ready to scale with Redis session management
✅ Designed for production use with extensibility


# Tech Stack
Area	Tech
Backend	FastAPI, Python
Messaging	Twilio WhatsApp API
NLP	Rasa
Database	MySQL
Session	Redis (optional)
Payment	Razorpay
PDF	reportlab or fpdf
Frontend Form	HTML, JS, CSS

# Conversation Flow (User Journey)
User sends “hi” on WhatsApp

Bot replies with menu: Book Bus / Flight

Asks for source → destination → date

Shows available options with timing & prices

User selects one → confirms → enters passenger details

Razorpay payment link is sent

On successful payment → ticket is generated & sent as PDF
