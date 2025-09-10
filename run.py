import json
import smtplib
from email.mime.text import MIMEText
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from openai import OpenAI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from datetime import datetime
import uuid
import logging
import re
import os
from dotenv import load_dotenv
# Set up logging
load_dotenv()  # Load environment variables from .env file
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize OpenAI Grok client
try:
    api_key = os.getenv("XAI_API_KEY")  # Load API key from environment variable
    print(api_key)
    if not api_key:
        raise ValueError("XAI_API_KEY environment variable not set")
    client = OpenAI(
        api_key=api_key,
        base_url="https://api.x.ai/v1"
    )
except Exception as e:
    logger.error(f"Failed to initialize OpenAI client: {str(e)}")
    raise

# FastAPI app setup
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Session data structure
conversation_data = {}

# Pydantic models
class QueryRequest(BaseModel):
    query: str
    session_id: str = None

class AppointmentRequest(BaseModel):
    session_id: str
    preferred_day: str
    preferred_time: str
    full_name: str
    email: str
    phone: str

# Suggestions for initial step only
initial_suggestions = ["Digital Marketing", "Brand", "Custom Software Development/Mobile Application Development", "Website Design"]

# Helper functions
def initialize_session():
    session_id = str(uuid.uuid4())
    conversation_data[session_id] = {
        "history": [],
        "state": {
            "full_name": None,
            "email": None,
            "phone": None,
            "service": None,
            "mode": "initial",
            "error": None,
            "answered_questions": {},  # Kept for email compatibility, even if empty
        }
    }
    return session_id

def send_appointment_email(session_id, full_name, email, phone, preferred_day, preferred_time):
    try:
        # Email configuration
        smtp_server = "smtp.hostinger.com"
        smtp_port = 587
        sender_email = "info@omnisuiteai.com"
        sender_password = "Legacymasdasdasd23!!"
        recipient_emails = ["info@omnisuiteai.com"]
        if email:
            recipient_emails.append(email)

        # Retrieve answers from session (will be empty, but kept for compatibility)
        state = conversation_data[session_id]["state"]
        answers = state["answered_questions"]

        # Email content
        subject = f"Appointment Confirmation for {full_name or 'Client'} on {preferred_day}"
        body = f"""
Dear {full_name or 'Client'},

Thank you for booking an appointment with Omni Suite AI. Below are the details of your appointment:

**Appointment Details:**
- Date: {preferred_day}
- Time: {preferred_time}
- Session ID: {session_id}

**Client Information:**
- Name: {full_name or 'Not provided'}
- Email: {email or 'Not provided'}
- Phone: {phone or 'Not provided'}

**Service Information:**
- Selected Service: {state['service'] or 'Not provided'}
- Answers: {json.dumps(answers, indent=2)}

We will contact you to confirm this appointment. If you need to reschedule or have any questions, please reach out to us at info@omnisuiteai.com.

Best regards,
Omni Suite AI
"""
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = sender_email
        msg["To"] = ", ".join(recipient_emails)

        # Connect to SMTP server
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, recipient_emails, msg.as_string())
        logger.info(f"Email sent successfully to {', '.join(recipient_emails)} for appointment on {preferred_day} at {preferred_time}")
    except Exception as e:
        logger.error(f"Failed to send appointment email: {str(e)}")
        pass

def get_next_question_and_suggestions(state):
    error = state.get("error")

    if error:
        return error, []

    if state["mode"] == "initial":
        return (
            "Hello, and welcome to Omni Suite AI!\n\nMy name is Charles. How can I help you today?\n\nDo you need support with any of the following?\n- Digital Marketing\n- Brand\n- Custom Software Development/Mobile Application Development\n- Website Design",
            initial_suggestions
        )
    else:
        # In conversational mode, no fixed question or suggestions
        return None, []

def ask_grok(session_id, user_input):
    if session_id not in conversation_data:
        logger.error(f"Invalid session_id: {session_id}")
        return "Session not found. Please start a new conversation.", []

    state = conversation_data[session_id]["state"]
    state["error"] = None  # Clear any previous error
    
    # Update state based on user input
    if user_input:
        conversation_data[session_id]["history"].append({"role": "user", "content": user_input})
        if state["mode"] == "initial":
            normalized_input = user_input.lower().strip()
            valid_services = [service.lower() for service in initial_suggestions]
            if normalized_input in valid_services:
                state["service"] = initial_suggestions[valid_services.index(normalized_input)]
                state["mode"] = "conversational"
            else:
                state["error"] = "Please select one of the following: Digital Marketing, Brand, Custom Software Development/Mobile Application Development, or Website Design."
                return state["error"], []

    # Prepare system prompt
    next_question, suggestions = get_next_question_and_suggestions(state)
    if state["mode"] == "initial":
        system_prompt = {
            "role": "system",
            "content": f"""
You're a friendly marketing assistant for Omni Suite AI named Charles.
Ask this question or provide this information: "{next_question}"
Keep responses short (2-3 sentences), professional, and engaging.
"""
        }
    else:
        booking_message = "Please provide your full name, email address, phone number, and preferred day and time for a session with our Strategy Director, Ryan Jenkins."
        system_prompt = {
            "role": "system",
            "content": f"""
You're a friendly marketing assistant for Omni Suite AI named Charles, specialized as a master in {state['service']}.
Help the user with their queries and problems related to {state['service']}, providing knowledgeable answers based on best practices in the domain.
Keep responses short (2-3 sentences), professional, and engaging.
If you cannot fully resolve the user's issue based on the conversation, or if they need more in-depth, personalized assistance, or if the problem persists, offer to book a session by exactly saying: "{booking_message}"
"""
        }

    # Get response from Grok
    try:
        response = client.chat.completions.create(
            model="grok-2-latest",
            messages=[system_prompt] + conversation_data[session_id]["history"][-15:]
        )
        reply = response.choices[0].message.content
        conversation_data[session_id]["history"].append({"role": "assistant", "content": reply})
        conversation_data[session_id]["history"] = conversation_data[session_id]["history"][-15:]
        return reply, suggestions
    except Exception as e:
        logger.error(f"Error calling Grok API: {str(e)}")
        fallback_reply = "Sorry, something went wrong while processing your request. Please try again or contact support."
        conversation_data[session_id]["history"].append({"role": "assistant", "content": fallback_reply})
        conversation_data[session_id]["history"] = conversation_data[session_id]["history"][-15:]
        return fallback_reply, suggestions

# API endpoints
@app.post("/query")
async def query_chat(request: QueryRequest):
    try:
        session_id = request.session_id or initialize_session()
        reply, suggestions = ask_grok(session_id, request.query)
        return {"message": reply, "session_id": session_id, "suggestions": suggestions}
    except Exception as e:
        logger.error(f"Error processing query: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error processing query: {str(e)}")

@app.post("/book_appointment")
async def book_appointment(request: AppointmentRequest):
    try:
        session_id = request.session_id
        appointment_date = datetime.strptime(request.preferred_day, "%Y-%m-%d")
        # Validate email format
        email_regex = r'^\w+([\.-]?\w+)*@\w+([\.-]?\w+)*(\.\w{2,3})+$'
        if not re.match(email_regex, request.email):
            raise HTTPException(status_code=400, detail="Invalid email format. Please provide a valid email address.")
        # Update session state with user details
        conversation_data[session_id]["state"]["full_name"] = request.full_name
        conversation_data[session_id]["state"]["email"] = request.email
        conversation_data[session_id]["state"]["phone"] = request.phone
        confirmation = f"Appointment booked for {request.preferred_day} at {request.preferred_time}. We'll contact you to confirm!"
        conversation_data[session_id]["history"].append({"role": "assistant", "content": confirmation})
        conversation_data[session_id]["state"]["answered_questions"]["confirmation"] = confirmation
        conversation_data[session_id]["history"] = conversation_data[session_id]["history"][-15:]

        # Send email notification
        send_appointment_email(session_id, request.full_name, request.email, request.phone, request.preferred_day, request.preferred_time)

        return {"message": confirmation}
    except ValueError:
        logger.error("Invalid date format provided")
        raise HTTPException(status_code=400, detail="Invalid date format. Please use YYYY-MM-DD.")
    except Exception as e:
        logger.error(f"Error booking appointment: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error booking appointment: {str(e)}")

@app.get("/")
async def welcome():
    return {"message": "Welcome to Omni Suite AI's Chatbot!"}

# Run app
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=7008)