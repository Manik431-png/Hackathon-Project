from datetime import datetime
import hashlib
import html
import hmac
from io import BytesIO
import json
import math
import re
from pathlib import Path
import pickle
import secrets
import sqlite3
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus, urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from fpdf import FPDF
from PIL import Image, ImageOps
from assistant_memory import get_memory, save_memory, update_memory, MemoryResult
from vectorstore import get_vectorstore


MODEL_PATH = Path("model.pkl")
X_RAY_MODEL_PATH = Path("xray_model.pkl")
DATA_PATH = Path("heart.csv")
USER_DB_PATH = Path("users.db")
PATIENTS_CSV = Path("patients.csv")
INSIGHTS_PUBLIC_URL = "https://thorecoin.com/"
INSIGHTS_EMBED_URL = "https://i-nsights-your-ai-life-os-91a60e24.base44.app/"
NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_SEARCH_URL = "https://overpass-api.de/api/interpreter"
APP_USER_AGENT = "CardioInsightAI/1.0 (educational Streamlit app)"

HOSPITAL_NAME = "CardioCare General Hospital"
HOSPITAL_ADDRESS = "12 Health Avenue, New Delhi"
HOSPITAL_CONTACT = "Phone: +91 98765 43210 | Email: cardiocare@example.com"

FEATURE_COLUMNS = [
    "age",
    "sex",
    "cp",
    "trestbps",
    "chol",
    "fbs",
    "restecg",
    "thalach",
    "exang",
    "oldpeak",
    "slope",
    "ca",
    "thal",
]

FEATURE_LABELS = {
    "age": "Age",
    "sex": "Gender",
    "cp": "Chest Pain Type",
    "trestbps": "Resting Blood Pressure",
    "chol": "Cholesterol",
    "fbs": "Fasting Blood Sugar > 120",
    "restecg": "Resting ECG",
    "thalach": "Maximum Heart Rate",
    "exang": "Exercise Induced Angina",
    "oldpeak": "Oldpeak",
    "slope": "Slope",
    "ca": "Major Vessels",
    "thal": "Thal",
}

GENDER_LABELS = {0: "Female", 1: "Male"}
YES_NO_LABELS = {0: "No", 1: "Yes"}
CP_LABELS = {
    0: "Typical angina",
    1: "Atypical angina",
    2: "Non-anginal pain",
    3: "Asymptomatic",
}
RESTECG_LABELS = {
    0: "Normal",
    1: "ST-T wave abnormality",
    2: "Left ventricular hypertrophy",
}
SLOPE_LABELS = {
    0: "Upsloping",
    1: "Flat",
    2: "Downsloping",
}
THAL_LABELS = {
    0: "Unknown",
    1: "Normal",
    2: "Fixed defect",
    3: "Reversible defect",
}
BENCHMARK_FEATURES = ["age", "trestbps", "chol", "thalach", "oldpeak"]
LOW_RISK_MAX = 0.35
MEDIUM_RISK_MAX = 0.65
PASSWORD_ITERATIONS = 200_000
DOCTOR_SEARCH_RADIUS_METERS = 12000
X_RAY_TARGET_SIZE = (224, 224)
X_RAY_SUMMARY_COLUMNS = [
    "mean_intensity",
    "std_intensity",
    "min_intensity",
    "max_intensity",
    "center_mean",
    "upper_mean",
    "lower_mean",
    "left_mean",
    "right_mean",
    "edge_mean",
    "gradient_strength",
]
SYMPTOM_FIELDS = [
    ("chest_pain", "Chest pain", 3),
    ("shortness_of_breath", "Shortness of breath", 3),
    ("fatigue", "Fatigue", 1),
    ("dizziness", "Dizziness", 2),
    ("irregular_heartbeat", "Irregular heartbeat", 3),
    ("sweating", "Sweating", 2),
    ("nausea", "Nausea", 1),
    ("pain_left_arm_jaw", "Pain in left arm or jaw", 3),
]
SERIOUS_SYMPTOMS = {
    "chest_pain",
    "shortness_of_breath",
    "irregular_heartbeat",
    "pain_left_arm_jaw",
}
MAJOR_SYMPTOMS = SERIOUS_SYMPTOMS | {"dizziness", "sweating"}
CHAT_SYMPTOM_KEYWORDS = [
    "chest pain",
    "shortness of breath",
    "fatigue",
    "dizziness",
    "irregular heartbeat",
    "sweating",
    "nausea",
    "pain in left arm",
    "pain in jaw",
    "pressure",
    "tightness",
]


def normalize_email(email):
    return email.strip().lower()


def get_auth_connection():
    connection = sqlite3.connect(USER_DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_auth_db():
    with get_auth_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.commit()


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    derived_key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        PASSWORD_ITERATIONS,
    ).hex()
    return f"{salt}${derived_key}"


def verify_password(password, stored_hash):
    try:
        salt, expected_hash = stored_hash.split("$", maxsplit=1)
    except ValueError:
        return False

    current_hash = hash_password(password, salt).split("$", maxsplit=1)[1]
    return hmac.compare_digest(current_hash, expected_hash)


def get_user_by_email(email):
    with get_auth_connection() as connection:
        return connection.execute(
            "SELECT id, full_name, email, password_hash, created_at FROM users WHERE email = ?",
            (normalize_email(email),),
        ).fetchone()


def create_user(full_name, email, password):
    normalized_email = normalize_email(email)
    if not full_name.strip():
        return None, "Please enter your full name."
    if not normalized_email:
        return None, "Please enter your email address."
    if len(password) < 6:
        return None, "Password must be at least 6 characters long."
    if get_user_by_email(normalized_email):
        return None, "An account with this email already exists."

    password_hash = hash_password(password)
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with get_auth_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO users (full_name, email, password_hash, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (full_name.strip(), normalized_email, password_hash, created_at),
        )
        connection.commit()
        user_id = cursor.lastrowid

    return {
        "id": user_id,
        "full_name": full_name.strip(),
        "email": normalized_email,
        "created_at": created_at,
    }, None


def save_patient_data(patient_data):
    df = pd.DataFrame([patient_data])
    if PATIENTS_CSV.exists():
        existing_df = pd.read_csv(PATIENTS_CSV)
        df = pd.concat([existing_df, df], ignore_index=True)
    df.to_csv(PATIENTS_CSV, index=False)


def authenticate_user(email, password):
    user = get_user_by_email(email)
    if not user or not verify_password(password, user["password_hash"]):
        return None, "Invalid email or password."

    return {
        "id": user["id"],
        "full_name": user["full_name"],
        "email": user["email"],
        "created_at": user["created_at"],
    }, None


def initialize_auth_state():
    if "auth_user" not in st.session_state:
        st.session_state.auth_user = None


def start_user_session(user):
    st.session_state.auth_user = user
    st.session_state.patient_id = generate_patient_id()
    st.session_state.assessment_history = []
    st.session_state.latest_assessment = None
    st.session_state.latest_xray_assessment = None


def logout_user():
    st.session_state.auth_user = None
    st.session_state.patient_id = generate_patient_id()
    st.session_state.assessment_history = []
    st.session_state.latest_assessment = None
    st.session_state.latest_xray_assessment = None


def _safe_extract_name(message: str):
    patterns = [
        r"my name is (?P<name>[A-Za-z ]+)",
        r"i am (?P<name>[A-Za-z ]+)",
        r"i'm (?P<name>[A-Za-z ]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            name = match.group("name").strip()
            if len(name) > 1:
                return name.title()
    return None


def _find_symptoms(message: str):
    text = message.lower()
    symptoms = []
    for keyword in CHAT_SYMPTOM_KEYWORDS:
        if keyword in text and keyword not in symptoms:
            symptoms.append(keyword)
    return symptoms


def _read_chat_memory(user_id: str, key: str):
    result = get_memory(user_id, key)
    return result.value if result else None


def _store_chat_memory(user_id: str, key: str, value):
    existing = _read_chat_memory(user_id, key)
    if existing is None:
        save_memory(user_id, key, value)
    else:
        update_memory(user_id, key, value)
    return {
        "user_id": user_id,
        "key": key,
        "value": value,
    }


def _merge_symptom_lists(existing, new_symptoms):
    merged = list(dict.fromkeys((existing or []) + new_symptoms))
    return merged


def _build_chat_greeting(user_id: str) -> str:
    name = _read_chat_memory(user_id, "name")
    if name:
        return f"Hello again, {name}! I'm your Hindsight health assistant."
    return "Hello! I'm your Hindsight health assistant. Tell me about your symptoms, risk, or what you'd like to learn."


def _build_chat_response(message: str, user_id: str) -> dict:
    normalized = message.strip()
    details = {"memory_actions": []}
    vectorstore = get_vectorstore()

    name = _safe_extract_name(normalized)
    if name:
        _store_chat_memory(user_id, "name", name)
        details["memory_actions"].append({"key": "name", "value": name})
        return {
            "response": f"Nice to meet you, {name}. I will remember your name for future conversations.",
            "details": details,
        }

    if re.search(r"what is my name|who am i|do you know my name", normalized, re.IGNORECASE):
        stored_name = _read_chat_memory(user_id, "name")
        if stored_name:
            return {"response": f"Your name is {stored_name}.", "details": details}
        return {"response": "I don't have your name yet. Please tell me your name.", "details": details}

    symptoms = _find_symptoms(normalized)
    if symptoms:
        existing_symptoms = _read_chat_memory(user_id, "symptoms") or []
        merged = _merge_symptom_lists(existing_symptoms, symptoms)
        _store_chat_memory(user_id, "symptoms", merged)
        details["memory_actions"].append({"key": "symptoms", "value": merged})
        return {
            "response": f"I've noted your symptoms: {', '.join(merged)}. I can also compare these to similar past cases if you want.",
            "details": details,
        }

    if re.search(r"similar cases|similar patients|past cases|history|learn from past|learn from history", normalized, re.IGNORECASE):
        patterns = vectorstore.learn_patterns()
        if patterns.get("status") == "insufficient_data":
            return {
                "response": f"I need at least 5 stored patient records to learn meaningful patterns. Currently I have {patterns.get('count', 0)}.",
                "details": details,
            }
        return {
            "response": (
                f"I have learned from {patterns.get('total_patients', 0)} patients. "
                f"The system has found {len(patterns.get('clusters', []))} patient clusters and a mean population profile. "
                "If you give me a patient ID, I can compare it to similar historical cases."
            ),
            "details": details,
        }

    if re.search(r"risk|heart risk|predict|prediction", normalized, re.IGNORECASE):
        previous_risk = _read_chat_memory(user_id, "previous_risk")
        if previous_risk is not None:
            return {
                "response": f"Your last recorded risk score is {float(previous_risk):.1%}. If you want, provide updated measurements and I can compare a new prediction.",
                "details": details,
            }
        return {"response": "I don't have a saved risk score yet. Run a prediction in the Prediction Studio first.", "details": details}

    if re.search(r"memory|remember|forgot|do you know", normalized, re.IGNORECASE):
        profile = {
            "name": _read_chat_memory(user_id, "name"),
            "age": _read_chat_memory(user_id, "age"),
            "symptoms": _read_chat_memory(user_id, "symptoms"),
            "previous_risk": _read_chat_memory(user_id, "previous_risk"),
        }
        profile_lines = [f"{key.capitalize()}: {value}" for key, value in profile.items() if value is not None]
        if profile_lines:
            return {"response": "I remember: " + "; ".join(profile_lines), "details": details}
        return {"response": "I don't have any memory for you yet. Share your name, age, symptoms, or risk information.", "details": details}

    if re.search(r"hello|hi|hey|good morning|good evening", normalized, re.IGNORECASE):
        return {"response": _build_chat_greeting(user_id), "details": details}

    return {
        "response": _build_chat_greeting(user_id) + " Tell me what you'd like to discuss about your heart health.",
        "details": details,
    }


def initialize_chat_state():
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    if "chat_user_id" not in st.session_state:
        st.session_state.chat_user_id = "user-001"


def _render_chat_history():
    for message in st.session_state.chat_history:
        speaker = message.get("speaker")
        text = message.get("message")
        if speaker == "You":
            st.markdown(f"**You:** {text}")
        else:
            st.markdown(f"**HealthBot:** {text}")


def _render_memory_snapshot(user_id: str):
    st.markdown("### Saved Hindsight Memory")
    for key in ["name", "age", "symptoms", "previous_risk"]:
        value = _read_chat_memory(user_id, key)
        st.write(f"- **{key.replace('_', ' ').title()}:** {value if value is not None else 'No data saved yet.'}")


def render_auth_screen():
    st.markdown(
        """
        <div class="hero-card">
            <div class="hero-eyebrow">Secure Access</div>
            <div class="hero-title">Login or create an account</div>
            <div class="hero-subtitle">
                Sign in to open the advanced CardioInsight AI workspace with prediction history,
                downloadable reports, and your personalized screening dashboard.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    info_col, auth_col = st.columns([1, 1.15], gap="large")
    with info_col:
        st.markdown(
            """
            <div class="panel-card">
                <div class="panel-title">What unlocks after sign in</div>
                <div class="panel-text">
                    Access the heart risk prediction studio, clinician handoff notes, PDF exports,
                    benchmark comparisons, iNSIGHTS integration, and a private session workspace.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown(
            """
            <div class="panel-card">
                <div class="panel-title">Built for your project demo</div>
                <div class="panel-text">
                    The new authentication layer gives your app a more complete product feel and
                    keeps the advanced dashboard behind a proper login flow.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with auth_col:
        login_tab, signup_tab = st.tabs(["Login", "Sign Up"])

        with login_tab:
            with st.form("login_form"):
                login_email = st.text_input("Email", placeholder="you@example.com")
                login_password = st.text_input("Password", type="password", placeholder="Enter your password")
                login_submitted = st.form_submit_button("Login", use_container_width=True)

            if login_submitted:
                user, error_message = authenticate_user(login_email, login_password)
                if error_message:
                    st.error(error_message)
                else:
                    start_user_session(user)
                    st.rerun()

        with signup_tab:
            with st.form("signup_form"):
                signup_name = st.text_input("Full name", placeholder="Your name")
                signup_email = st.text_input("Email address", placeholder="you@example.com")
                signup_password = st.text_input("Create password", type="password", placeholder="At least 6 characters")
                signup_confirm = st.text_input("Confirm password", type="password", placeholder="Re-enter password")
                signup_submitted = st.form_submit_button("Create Account", use_container_width=True)

            if signup_submitted:
                if signup_password != signup_confirm:
                    st.error("Passwords do not match.")
                else:
                    user, error_message = create_user(signup_name, signup_email, signup_password)
                    if error_message:
                        st.error(error_message)
                    else:
                        start_user_session(user)
                        st.success("Account created successfully.")
                        st.rerun()


def inject_css():
    st.markdown(
        """
        <style>
            :root {
                --bg-soft: #eef4fb;
                --surface: rgba(255, 255, 255, 0.9);
                --surface-strong: #ffffff;
                --border-soft: rgba(148, 163, 184, 0.28);
                --border-strong: #cbd5e1;
                --ink-primary: #0f172a;
                --ink-secondary: #475569;
                --brand-primary: #1d4ed8;
                --brand-accent: #0f766e;
                --brand-soft: #dbeafe;
                --shadow-soft: 0 18px 40px rgba(15, 23, 42, 0.08);
            }
            .stApp {
                background:
                    radial-gradient(circle at top left, rgba(255, 107, 107, 0.14), transparent 28%),
                    radial-gradient(circle at top right, rgba(93, 173, 226, 0.16), transparent 24%),
                    linear-gradient(180deg, #f6f8fc 0%, #eef3f8 100%);
                color: var(--ink-primary);
            }
            .block-container {
                padding-top: 2rem;
                padding-bottom: 2rem;
                max-width: 1180px;
            }
            .hero-card {
                background: linear-gradient(135deg, #0f172a 0%, #172554 45%, #1d4ed8 100%);
                color: white;
                border-radius: 24px;
                padding: 1.6rem 1.8rem;
                box-shadow: 0 24px 60px rgba(15, 23, 42, 0.24);
                margin-bottom: 1rem;
            }
            .hero-eyebrow {
                font-size: 0.82rem;
                text-transform: uppercase;
                letter-spacing: 0.08em;
                opacity: 0.8;
            }
            .hero-title {
                font-size: 2rem;
                font-weight: 800;
                margin-top: 0.35rem;
                margin-bottom: 0.45rem;
            }
            .hero-subtitle {
                font-size: 1rem;
                opacity: 0.92;
                max-width: 760px;
            }
            .glass-card {
                background: rgba(255, 255, 255, 0.84);
                backdrop-filter: blur(8px);
                border: 1px solid rgba(148, 163, 184, 0.2);
                border-radius: 22px;
                padding: 1rem 1.1rem;
                box-shadow: 0 16px 40px rgba(15, 23, 42, 0.08);
            }
            .metric-card {
                background: white;
                border-radius: 20px;
                padding: 1rem 1.1rem;
                border: 1px solid rgba(226, 232, 240, 0.9);
                box-shadow: 0 12px 28px rgba(15, 23, 42, 0.06);
            }
            .metric-label {
                color: #475569;
                font-size: 0.9rem;
                margin-bottom: 0.3rem;
            }
            .metric-value {
                color: #0f172a;
                font-size: 1.8rem;
                font-weight: 800;
                line-height: 1.1;
            }
            .status-pill {
                display: inline-block;
                border-radius: 999px;
                padding: 0.35rem 0.75rem;
                font-weight: 700;
                font-size: 0.88rem;
                margin-bottom: 0.8rem;
            }
            .status-high {
                background: rgba(239, 68, 68, 0.14);
                color: #b91c1c;
            }
            .status-medium {
                background: rgba(245, 158, 11, 0.16);
                color: #b45309;
            }
            .status-low {
                background: rgba(34, 197, 94, 0.14);
                color: #166534;
            }
            .section-title {
                font-size: 1.15rem;
                font-weight: 800;
                color: #0f172a;
                margin-bottom: 0.65rem;
            }
            .info-chip {
                display: inline-block;
                padding: 0.45rem 0.7rem;
                margin: 0.25rem 0.4rem 0.25rem 0;
                border-radius: 999px;
                background: #e2e8f0;
                color: #0f172a;
                font-size: 0.85rem;
                font-weight: 600;
            }
            .panel-card {
                background: linear-gradient(180deg, rgba(255, 255, 255, 0.94) 0%, rgba(248, 250, 252, 0.96) 100%);
                border: 1px solid rgba(203, 213, 225, 0.8);
                border-radius: 22px;
                padding: 1rem 1.1rem;
                box-shadow: 0 12px 34px rgba(15, 23, 42, 0.06);
                margin-bottom: 1rem;
            }
            .panel-title {
                color: var(--ink-primary);
                font-size: 1rem;
                font-weight: 800;
                margin-bottom: 0.4rem;
            }
            .panel-text {
                color: var(--ink-secondary);
                font-size: 0.94rem;
                line-height: 1.55;
            }
            .auth-user-card {
                background: linear-gradient(180deg, rgba(255, 255, 255, 0.96) 0%, rgba(239, 246, 255, 0.96) 100%);
                border: 1px solid rgba(191, 219, 254, 0.9);
                border-radius: 20px;
                padding: 0.95rem 1rem;
                margin-bottom: 1rem;
                box-shadow: 0 12px 24px rgba(15, 23, 42, 0.06);
            }
            .auth-user-title {
                color: #0f172a;
                font-size: 0.78rem;
                text-transform: uppercase;
                letter-spacing: 0.08em;
                margin-bottom: 0.35rem;
            }
            .auth-user-name {
                color: #0f172a;
                font-size: 1.05rem;
                font-weight: 800;
                line-height: 1.2;
            }
            .auth-user-email {
                color: #475569;
                font-size: 0.88rem;
                margin-top: 0.2rem;
            }
            .stMarkdown,
            .stText,
            .stCaption,
            p,
            li,
            h1,
            h2,
            h3,
            h4 {
                color: var(--ink-primary);
            }
            [data-testid="stSidebar"] {
                background: linear-gradient(180deg, rgba(255, 255, 255, 0.94) 0%, rgba(239, 246, 255, 0.92) 100%);
                border-right: 1px solid rgba(191, 219, 254, 0.8);
            }
            [data-testid="stSidebar"] .stMarkdown,
            [data-testid="stSidebar"] p,
            [data-testid="stSidebar"] h1,
            [data-testid="stSidebar"] h2,
            [data-testid="stSidebar"] h3 {
                color: var(--ink-primary);
            }
            [data-testid="stWidgetLabel"] p {
                color: var(--ink-primary) !important;
                font-weight: 700 !important;
                font-size: 0.97rem !important;
                letter-spacing: 0.01em;
            }
            .stTextInput input,
            .stNumberInput input,
            div[data-baseweb="select"] > div,
            div[data-baseweb="base-input"] > div {
                background: rgba(255, 255, 255, 0.97) !important;
                color: var(--ink-primary) !important;
                border: 1px solid var(--border-strong) !important;
                border-radius: 14px !important;
                box-shadow: 0 8px 22px rgba(15, 23, 42, 0.06);
            }
            .stTextInput input,
            .stNumberInput input {
                min-height: 2.9rem;
            }
            .stTextInput input::placeholder,
            .stNumberInput input::placeholder {
                color: #64748b !important;
                opacity: 1 !important;
            }
            .stTextInput input:focus,
            .stNumberInput input:focus {
                border-color: var(--brand-primary) !important;
                box-shadow: 0 0 0 0.22rem rgba(29, 78, 216, 0.14) !important;
            }
            .stTextInput input:disabled,
            .stNumberInput input:disabled {
                color: #1e293b !important;
                -webkit-text-fill-color: #1e293b !important;
                background: #e2e8f0 !important;
                opacity: 1 !important;
            }
            div[data-baseweb="select"] * {
                color: var(--ink-primary) !important;
            }
            div[data-baseweb="select"] svg {
                fill: var(--brand-primary) !important;
            }
            .stForm {
                background: rgba(255, 255, 255, 0.52);
                border: 1px solid var(--border-soft);
                border-radius: 24px;
                padding: 1.3rem 1.2rem 1.1rem;
                margin-top: 1rem;
                box-shadow: var(--shadow-soft);
            }
            .stTabs [data-baseweb="tab-list"] {
                gap: 0.45rem;
                background: rgba(226, 232, 240, 0.7);
                padding: 0.35rem;
                border-radius: 18px;
            }
            .stTabs [data-baseweb="tab"] {
                height: auto;
                padding: 0.75rem 1rem;
                border-radius: 14px;
                color: var(--ink-secondary);
                font-weight: 700;
            }
            .stTabs [aria-selected="true"] {
                background: rgba(255, 255, 255, 0.95) !important;
                color: var(--ink-primary) !important;
                box-shadow: 0 10px 24px rgba(15, 23, 42, 0.08);
            }
            .stButton button,
            .stFormSubmitButton button,
            .stDownloadButton button,
            .stLinkButton a {
                background: linear-gradient(135deg, var(--brand-accent) 0%, var(--brand-primary) 100%) !important;
                color: white !important;
                border: none !important;
                border-radius: 14px !important;
                font-weight: 700 !important;
                box-shadow: 0 16px 28px rgba(29, 78, 216, 0.18);
                transition: transform 0.2s ease, box-shadow 0.2s ease;
            }
            .stButton button:hover,
            .stFormSubmitButton button:hover,
            .stDownloadButton button:hover,
            .stLinkButton a:hover {
                transform: translateY(-1px);
                box-shadow: 0 20px 32px rgba(29, 78, 216, 0.22);
            }
            .stDataFrame,
            [data-testid="stTable"] {
                background: rgba(255, 255, 255, 0.72);
                border-radius: 18px;
                padding: 0.35rem;
                box-shadow: 0 10px 28px rgba(15, 23, 42, 0.05);
            }
            [data-testid="stMetric"] {
                background: rgba(255, 255, 255, 0.76);
                border: 1px solid rgba(226, 232, 240, 0.9);
                padding: 0.8rem 1rem;
                border-radius: 18px;
                box-shadow: 0 12px 28px rgba(15, 23, 42, 0.05);
            }
            hr {
                border-color: rgba(148, 163, 184, 0.35);
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


@st.cache_data
def load_reference_data():
    if DATA_PATH.exists():
        return pd.read_csv(DATA_PATH)
    return pd.DataFrame(columns=FEATURE_COLUMNS + ["target"])


def build_fallback_bundle(model):
    df = load_reference_data()
    class_profiles = {}
    class_distribution = {}

    if not df.empty:
        class_profiles = (
            df.groupby("target")[FEATURE_COLUMNS]
            .mean()
            .round(4)
            .to_dict(orient="index")
        )
        class_distribution = {int(key): int(value) for key, value in df["target"].value_counts().sort_index().items()}

    return {
        "model": model,
        "model_name": type(model).__name__,
        "feature_columns": FEATURE_COLUMNS,
        "disease_class": 0,
        "healthy_class": 1,
        "metrics": {},
        "feature_importance": {},
        "class_profiles": class_profiles,
        "dataset_summary": {"class_distribution": class_distribution},
        "preprocessing": [],
    }


@st.cache_resource
def load_model_bundle():
    if not MODEL_PATH.exists():
        raise FileNotFoundError("model.pkl was not found. Run train_model.py to generate the improved model first.")

    with MODEL_PATH.open("rb") as file:
        artifact = pickle.load(file)

    if isinstance(artifact, dict) and "model" in artifact:
        bundle = artifact
    else:
        bundle = build_fallback_bundle(artifact)

    bundle["disease_class"] = int(bundle.get("disease_class", 0))
    bundle["healthy_class"] = int(bundle.get("healthy_class", 1))
    bundle["feature_columns"] = bundle.get("feature_columns", FEATURE_COLUMNS)
    bundle["class_profiles"] = {
        int(key): value for key, value in bundle.get("class_profiles", {}).items()
    }
    bundle["dataset_summary"] = bundle.get("dataset_summary", {})
    bundle["metrics"] = bundle.get("metrics", {})
    bundle["feature_importance"] = bundle.get("feature_importance", {})
    bundle["preprocessing"] = bundle.get("preprocessing", [])
    return bundle


class FallbackXrayRiskModel:
    """A lightweight fallback X-ray risk estimator for chest image screening."""

    def __init__(self):
        self.classes_ = np.array([0, 1], dtype=int)

    @staticmethod
    def _normalize_feature_frame(feature_frame):
        if isinstance(feature_frame, pd.DataFrame):
            feature_frame = feature_frame.to_numpy(dtype=np.float32)
        else:
            feature_frame = np.asarray(feature_frame, dtype=np.float32)

        if feature_frame.ndim == 1:
            feature_frame = feature_frame.reshape(1, -1)
        return feature_frame

    def _score(self, feature_frame):
        features = self._normalize_feature_frame(feature_frame)
        mean_intensity = np.clip(features[:, 0], 0.0, 1.0)
        std_intensity = np.clip(features[:, 1], 0.0, 1.0)
        edge_mean = np.clip(features[:, 9], 0.0, 1.0)
        gradient_strength = np.clip(features[:, 10], 0.0, 1.0)
        center_mean = np.clip(features[:, 4], 0.0, 1.0)

        base_score = (
            0.22 * mean_intensity
            + 0.20 * std_intensity
            + 0.18 * (1.0 - edge_mean)
            + 0.20 * gradient_strength
            + 0.20 * center_mean
        )
        return np.clip(base_score, 0.0, 1.0)

    def predict(self, feature_frame):
        scores = self._score(feature_frame)
        return self.classes_[(scores >= 0.5).astype(int)]

    def predict_proba(self, feature_frame):
        scores = self._score(feature_frame)
        probabilities = np.vstack([1.0 - scores, scores]).T
        return probabilities


def build_fallback_xray_bundle(model=None):
    fallback_model = model if model is not None else FallbackXrayRiskModel()
    return {
        "enabled": True,
        "model": fallback_model,
        "model_name": type(fallback_model).__name__,
        "feature_mode": "summary",
        "target_size": X_RAY_TARGET_SIZE,
        "feature_columns": X_RAY_SUMMARY_COLUMNS,
        "disease_class": 1,
        "healthy_class": 0,
        "class_labels": {
            0: "Lower heart disease risk pattern on chest X-ray",
            1: "Higher heart disease risk pattern on chest X-ray",
        },
        "preprocessing": [
            "Chest X-ray upload",
            "Grayscale normalization",
            "224 x 224 resize",
            "Summary feature extraction",
        ],
    }


def get_xray_model_signature():
    try:
        stats = X_RAY_MODEL_PATH.stat()
        return X_RAY_MODEL_PATH.resolve().as_posix(), stats.st_mtime, stats.st_size
    except OSError:
        return X_RAY_MODEL_PATH.resolve().as_posix(), None, None


@st.cache_resource
def load_xray_model_bundle(model_path, mtime, size):
    if not X_RAY_MODEL_PATH.exists():
        return build_fallback_xray_bundle()

    try:
        with X_RAY_MODEL_PATH.open("rb") as file:
            artifact = pickle.load(file)
    except Exception:
        return build_fallback_xray_bundle()

    if isinstance(artifact, dict) and "model" in artifact:
        bundle = build_fallback_xray_bundle(artifact.get("model"))
        bundle.update(artifact)
        bundle["enabled"] = bundle.get("model") is not None
    else:
        bundle = build_fallback_xray_bundle(artifact)

    target_size = bundle.get("target_size", X_RAY_TARGET_SIZE)
    if isinstance(target_size, int):
        bundle["target_size"] = (target_size, target_size)
    else:
        bundle["target_size"] = tuple(target_size)

    bundle["feature_columns"] = bundle.get("feature_columns") or X_RAY_SUMMARY_COLUMNS
    bundle["feature_mode"] = bundle.get("feature_mode", "summary")
    bundle["preprocessing"] = bundle.get("preprocessing") or []
    bundle["class_labels"] = bundle.get("class_labels") or {}
    return bundle


def open_xray_images(uploaded_file):
    image_bytes = uploaded_file.getvalue()
    preview_image = Image.open(BytesIO(image_bytes))
    preview_image = ImageOps.exif_transpose(preview_image).convert("RGB")
    grayscale_image = preview_image.convert("L")
    return image_bytes, preview_image, grayscale_image


def get_xray_quality_flags(grayscale_image):
    pixel_array = np.asarray(grayscale_image, dtype=np.float32)
    width, height = grayscale_image.size
    mean_intensity = float(pixel_array.mean())
    contrast = float(pixel_array.std())
    flags = []

    if min(width, height) < 256:
        flags.append(("warning", "Image resolution is low, so the screening result may be less reliable."))
    else:
        flags.append(("success", "Image resolution is acceptable for lightweight screening preprocessing."))

    if mean_intensity < 45:
        flags.append(("warning", "The X-ray appears quite dark and may hide important structures."))
    elif mean_intensity > 210:
        flags.append(("warning", "The X-ray appears very bright, which can reduce visible detail."))
    else:
        flags.append(("success", "Overall image brightness is within a workable range."))

    if contrast < 18:
        flags.append(("warning", "Image contrast is low, so the heart outline may be difficult to distinguish."))
    else:
        flags.append(("success", "Image contrast looks sufficient for simple screening."))

    return flags


def extract_xray_summary_features(normalized_array):
    height, width = normalized_array.shape
    center_slice = normalized_array[height // 4 : (height * 3) // 4, width // 4 : (width * 3) // 4]
    edge_mask = np.ones_like(normalized_array, dtype=bool)
    edge_mask[height // 5 : (height * 4) // 5, width // 5 : (width * 4) // 5] = False
    gradient_strength = float(
        np.mean(np.abs(np.diff(normalized_array, axis=0))) + np.mean(np.abs(np.diff(normalized_array, axis=1)))
    )

    return {
        "mean_intensity": float(normalized_array.mean()),
        "std_intensity": float(normalized_array.std()),
        "min_intensity": float(normalized_array.min()),
        "max_intensity": float(normalized_array.max()),
        "center_mean": float(center_slice.mean()),
        "upper_mean": float(normalized_array[: height // 2, :].mean()),
        "lower_mean": float(normalized_array[height // 2 :, :].mean()),
        "left_mean": float(normalized_array[:, : width // 2].mean()),
        "right_mean": float(normalized_array[:, width // 2 :].mean()),
        "edge_mean": float(normalized_array[edge_mask].mean()),
        "gradient_strength": gradient_strength,
    }


def build_xray_feature_frame(grayscale_image, bundle):
    target_width, target_height = bundle.get("target_size", X_RAY_TARGET_SIZE)
    resized_image = ImageOps.fit(
        grayscale_image,
        (int(target_width), int(target_height)),
        method=Image.Resampling.BILINEAR,
    )
    normalized_array = np.asarray(resized_image, dtype=np.float32) / 255.0
    feature_mode = bundle.get("feature_mode", "summary")

    if feature_mode == "flatten_grayscale":
        flattened = normalized_array.flatten()
        feature_columns = bundle.get("feature_columns")
        if not feature_columns or len(feature_columns) != flattened.size:
            feature_columns = [f"pixel_{index}" for index in range(flattened.size)]
        return pd.DataFrame([flattened], columns=feature_columns), normalized_array

    summary_features = extract_xray_summary_features(normalized_array)
    feature_columns = bundle.get("feature_columns", X_RAY_SUMMARY_COLUMNS)
    return pd.DataFrame([{column: summary_features.get(column, 0.0) for column in feature_columns}]), normalized_array


def get_estimator_probability(model, feature_frame, target_class):
    if not hasattr(model, "predict_proba"):
        return None

    probabilities = model.predict_proba(feature_frame)[0]
    classes = list(getattr(model, "classes_", range(len(probabilities))))
    if target_class in classes:
        target_index = classes.index(target_class)
    else:
        target_index = int(np.argmax(probabilities))
    return float(probabilities[target_index])


def describe_xray_problem(finding_label, risk_band):
    finding_text = str(finding_label).lower()

    if "cardiomegaly" in finding_text or "enlarged" in finding_text:
        return "The X-ray pattern suggests possible enlargement of the cardiac silhouette, which can be associated with cardiomegaly or fluid-related strain."
    if "effusion" in finding_text or "fluid" in finding_text:
        return "The image label suggests possible fluid-related chest findings, which should be checked clinically because they can affect breathing and heart workload."
    if "congestion" in finding_text or "edema" in finding_text:
        return "The image pattern suggests possible pulmonary congestion, which may need urgent evaluation if symptoms are present."
    if risk_band == "Low":
        return "No major heart-related abnormality was flagged by the image screening model, but symptoms and clinical history still matter."
    return "The image screening model flagged a potentially relevant heart-related pattern that should be reviewed by a clinician."


def get_xray_next_steps(finding_label, risk_band):
    finding_text = str(finding_label).lower()
    steps = []

    if risk_band == "High":
        steps.extend(
            [
                "Arrange a prompt physician or cardiology review, especially if the patient has chest pain, breathlessness, swelling, or severe fatigue.",
                "Consider confirmatory tests such as ECG, echocardiography, blood pressure review, and oxygen saturation check.",
                "If symptoms are severe or rapidly worsening, seek urgent in-person care rather than relying on the app output.",
            ]
        )
    elif risk_band == "Medium":
        steps.extend(
            [
                "Schedule a clinician review and compare this X-ray result with symptoms, vitals, ECG findings, and prior history.",
                "Use follow-up tests such as ECG or echocardiography if the clinician suspects structural or functional heart changes.",
                "Monitor for chest pain, shortness of breath, palpitations, dizziness, or leg swelling and escalate if they appear.",
            ]
        )
    else:
        steps.extend(
            [
                "Keep routine follow-up and compare the image result with symptoms and the structured risk prediction module.",
                "Continue heart-healthy habits such as blood pressure control, medication adherence if prescribed, and regular activity as advised by a doctor.",
                "Seek clinical review if symptoms persist even when the image screen looks lower risk.",
            ]
        )

    if "cardiomegaly" in finding_text or "enlarged" in finding_text:
        steps.insert(1, "Ask for an echocardiogram if the clinician wants to confirm heart enlargement or pumping-function changes.")

    return steps


def analyze_xray_upload(uploaded_file, bundle):
    image_bytes, preview_image, grayscale_image = open_xray_images(uploaded_file)
    quality_flags = get_xray_quality_flags(grayscale_image)

    assessment = {
        "image_bytes": image_bytes,
        "image_size": preview_image.size,
        "quality_flags": quality_flags,
        "prediction_available": False,
        "model_name": bundle.get("model_name", "No X-ray model installed"),
        "preprocessing": bundle.get("preprocessing", []),
    }

    if not bundle.get("enabled"):
        assessment.update(
            {
                "risk_band": "Unavailable",
                "finding_label": "No X-ray model installed",
                "problem_summary": "The upload workflow is ready, but no trained chest X-ray model is available yet, so the app cannot generate a medical image finding.",
                "next_steps": [
                    "Add a trained artifact named xray_model.pkl to the project root to enable real image-based screening.",
                    "Until then, use the Prediction Studio and Symptom Checker for the current project demo.",
                    "Treat this section as infrastructure only, not a medical detector, until a validated X-ray model is connected.",
                ],
                "confidence_text": "Not available",
            }
        )
        return assessment, None

    try:
        feature_frame, _ = build_xray_feature_frame(grayscale_image, bundle)
        model = bundle["model"]
        prediction = model.predict(feature_frame)[0]
        disease_class = bundle.get("disease_class", prediction)
        probability = get_estimator_probability(model, feature_frame, disease_class)
        risk_band = get_risk_band(probability, prediction, disease_class)
        class_labels = bundle.get("class_labels", {})
        finding_label = class_labels.get(prediction, str(prediction))
        confidence_text = f"{probability * 100:.2f}%" if probability is not None else "Model confidence not provided"

        assessment.update(
            {
                "prediction_available": True,
                "prediction": prediction,
                "risk_probability": probability,
                "risk_band": risk_band,
                "finding_label": finding_label,
                "problem_summary": describe_xray_problem(finding_label, risk_band),
                "next_steps": get_xray_next_steps(finding_label, risk_band),
                "confidence_text": confidence_text,
            }
        )
        return assessment, None
    except Exception as error:
        return None, (
            "The X-ray model file was found, but prediction failed. "
            f"Please verify that `xray_model.pkl` matches the expected preprocessing pipeline. Details: {error}"
        )


def build_input_frame(
    age,
    sex,
    cp,
    trestbps,
    chol,
    fbs,
    restecg,
    thalach,
    exang,
    oldpeak,
    slope,
    ca,
    thal,
):
    return pd.DataFrame(
        [
            {
                "age": age,
                "sex": sex,
                "cp": cp,
                "trestbps": trestbps,
                "chol": chol,
                "fbs": fbs,
                "restecg": restecg,
                "thalach": thalach,
                "exang": exang,
                "oldpeak": oldpeak,
                "slope": slope,
                "ca": ca,
                "thal": thal,
            }
        ],
        columns=FEATURE_COLUMNS,
    )


def generate_patient_id():
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    suffix = uuid4().hex[:4].upper()
    return f"CCGH-{timestamp}-{suffix}"


def get_risk_probability(model, input_data, disease_class):
    if not hasattr(model, "predict_proba"):
        return None

    probabilities = model.predict_proba(input_data)[0]
    classes = list(model.classes_)
    disease_index = classes.index(disease_class)
    return float(probabilities[disease_index])


def format_feature_value(feature, value):
    if feature == "sex":
        return GENDER_LABELS.get(int(value), str(value))
    if feature in {"fbs", "exang"}:
        return YES_NO_LABELS.get(int(value), str(value))
    if feature == "cp":
        return CP_LABELS.get(int(value), str(value))
    if feature == "restecg":
        return RESTECG_LABELS.get(int(value), str(value))
    if feature == "slope":
        return SLOPE_LABELS.get(int(value), str(value))
    if feature == "thal":
        return THAL_LABELS.get(int(value), str(value))
    if feature == "oldpeak":
        return f"{float(value):.1f}"
    return str(int(value)) if float(value).is_integer() else f"{float(value):.2f}"


def explain_feature(feature, value, supports_risk):
    direction = "higher-risk" if supports_risk else "lower-risk"

    if feature == "trestbps":
        return f"Resting blood pressure is trending toward the {direction} patient profile."
    if feature == "chol":
        return f"Cholesterol level is closer to the {direction} cases in the training data."
    if feature == "thalach":
        return f"Maximum heart rate aligns more with the {direction} profile."
    if feature == "oldpeak":
        return f"Oldpeak suggests the stress-response pattern seen in the {direction} group."
    if feature == "ca":
        return f"Major vessel count is behaving like the {direction} examples."
    if feature == "exang":
        value_label = YES_NO_LABELS.get(int(value), str(value))
        return f"Exercise induced angina is marked as {value_label}, which supports the {direction} signal."
    if feature == "thal":
        value_label = THAL_LABELS.get(int(value), str(value))
        return f"Thal value ({value_label}) is closer to the {direction} pattern."
    if feature == "age":
        return f"Age is closer to the {direction} patient cluster."
    if feature == "cp":
        value_label = CP_LABELS.get(int(value), str(value))
        return f"Chest pain type ({value_label}) is contributing toward the {direction} decision."
    if feature == "fbs":
        value_label = YES_NO_LABELS.get(int(value), str(value))
        return f"Fasting blood sugar is {value_label}, which nudges the model toward the {direction} side."
    return f"{FEATURE_LABELS[feature]} is closer to the {direction} profile."


def get_prediction_insights(input_data, bundle, prediction):
    profiles = bundle.get("class_profiles", {})
    importances = bundle.get("feature_importance", {})
    disease_class = bundle.get("disease_class", 0)
    healthy_class = bundle.get("healthy_class", 1)

    if disease_class not in profiles or healthy_class not in profiles:
        return []

    row = input_data.iloc[0]
    signals = []
    prediction_supports_risk = prediction == disease_class

    for feature in bundle.get("feature_columns", FEATURE_COLUMNS):
        disease_mean = float(profiles[disease_class][feature])
        healthy_mean = float(profiles[healthy_class][feature])
        gap = abs(disease_mean - healthy_mean)
        if gap < 1e-6:
            continue

        value = float(row[feature])
        alignment = (abs(value - healthy_mean) - abs(value - disease_mean)) / gap
        weighted_score = alignment * float(importances.get(feature, 0.05))
        supports_risk = weighted_score > 0

        if supports_risk != prediction_supports_risk:
            continue

        signals.append(
            {
                "feature": feature,
                "score": abs(weighted_score),
                "message": explain_feature(feature, value, supports_risk),
            }
        )

    signals.sort(key=lambda item: item["score"], reverse=True)
    return [signal["message"] for signal in signals[:4]]


def get_patient_suggestions(input_data, risk_probability):
    row = input_data.iloc[0]
    suggestions = []

    if risk_probability is not None and risk_probability >= 0.65:
        suggestions.append("Book a cardiology consultation soon and review the result with a doctor.")
    if row["trestbps"] >= 140:
        suggestions.append("Resting blood pressure is elevated. Track BP regularly and discuss control strategies with your physician.")
    if row["chol"] >= 240:
        suggestions.append("Cholesterol is high. A lipid profile review, diet adjustment, and activity plan would be helpful.")
    if row["fbs"] == 1:
        suggestions.append("Fasting blood sugar is above the threshold. Monitor glucose and screen for diabetes risk.")
    if row["exang"] == 1 or row["oldpeak"] >= 2.0:
        suggestions.append("Exercise-related symptoms are present. Avoid intense unsupervised exertion until clinically reviewed.")
    if row["ca"] >= 2 or row["thal"] == 3:
        suggestions.append("Coronary vessel and thal-related markers look concerning. Imaging or stress testing may be worth discussing.")
    if row["thalach"] < 120:
        suggestions.append("Maximum heart rate is on the lower side for this profile. Ask about exercise tolerance and cardiac fitness assessment.")

    suggestions.append("Focus on sleep, hydration, tobacco avoidance, and a heart-friendly diet with lower saturated fat and sodium.")
    seen = set()
    deduped = []
    for suggestion in suggestions:
        if suggestion not in seen:
            deduped.append(suggestion)
            seen.add(suggestion)
    return deduped[:5]


def get_recommended_tests_from_prediction(input_data, risk_probability, risk_band):
    row = input_data.iloc[0]
    recommended_tests = []

    def add_test(test_name):
        if test_name not in recommended_tests:
            recommended_tests.append(test_name)

    if row["restecg"] != 0 or row["exang"] == 1 or risk_band in {"Medium", "High"}:
        add_test("ECG")
    if row["trestbps"] >= 130 or risk_band in {"Medium", "High"}:
        add_test("Blood Pressure test")
    if row["chol"] >= 200 or risk_band in {"Medium", "High"}:
        add_test("Cholesterol test")
    if row["exang"] == 1 or row["oldpeak"] >= 1.5 or row["thalach"] < 120 or risk_band == "High":
        add_test("Stress test")
    if row["ca"] >= 1 or row["thal"] in {2, 3} or row["restecg"] != 0 or risk_band == "High":
        add_test("Echocardiogram")

    if not recommended_tests and risk_probability is not None and risk_probability >= LOW_RISK_MAX:
        add_test("ECG")

    return recommended_tests


def get_provider_search_focus(risk_level):
    return "cardiologist" if risk_level in {"Medium", "High"} else "doctor"


def build_maps_search_url(query):
    return f"https://www.google.com/maps/search/?api=1&query={quote_plus(query)}"


def calculate_distance_km(lat1, lon1, lat2, lon2):
    earth_radius_km = 6371.0
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)

    delta_lat = lat2_rad - lat1_rad
    delta_lon = lon2_rad - lon1_rad
    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2
    )
    return earth_radius_km * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def format_provider_address(tags):
    address_parts = [
        tags.get("addr:housenumber"),
        tags.get("addr:street"),
        tags.get("addr:suburb"),
        tags.get("addr:city"),
        tags.get("addr:state"),
        tags.get("addr:postcode"),
    ]
    clean_parts = [part.strip() for part in address_parts if part and str(part).strip()]
    return ", ".join(clean_parts) if clean_parts else "Address details not available"


def get_provider_priority(tags, name):
    provider_blob = " ".join(
        [
            name or "",
            tags.get("healthcare:speciality", ""),
            tags.get("healthcare", ""),
            tags.get("amenity", ""),
            tags.get("description", ""),
            tags.get("department", ""),
        ]
    ).lower()
    score = 0
    if "cardio" in provider_blob or "heart" in provider_blob:
        score += 6
    if tags.get("amenity") == "hospital":
        score += 3
    if tags.get("amenity") == "clinic":
        score += 2
    if tags.get("amenity") == "doctors":
        score += 2
    if tags.get("healthcare") in {"doctor", "hospital", "clinic"}:
        score += 2
    return score


def get_provider_type_label(tags, name):
    provider_blob = " ".join(
        [
            name or "",
            tags.get("healthcare:speciality", ""),
            tags.get("description", ""),
            tags.get("department", ""),
        ]
    ).lower()
    if "cardio" in provider_blob or "heart" in provider_blob:
        return "Cardiology care"
    amenity = tags.get("amenity")
    healthcare = tags.get("healthcare")
    if amenity == "hospital" or healthcare == "hospital":
        return "Hospital"
    if amenity == "clinic" or healthcare == "clinic":
        return "Clinic"
    if amenity == "doctors" or healthcare == "doctor":
        return "Doctor"
    return "Medical provider"


def build_fallback_provider_links(location_query, search_focus):
    return [
        {
            "title": f"{search_focus.title()} near {location_query}",
            "subtitle": "Quick Maps search",
            "maps_url": build_maps_search_url(f"{search_focus} near {location_query}"),
        },
        {
            "title": f"Heart hospital near {location_query}",
            "subtitle": "Nearby hospital search",
            "maps_url": build_maps_search_url(f"heart hospital near {location_query}"),
        },
        {
            "title": f"ECG and cardiac test center near {location_query}",
            "subtitle": "Nearby diagnostic search",
            "maps_url": build_maps_search_url(f"ECG test center near {location_query}"),
        },
    ]


@st.cache_data(ttl=3600, show_spinner=False)
def get_nearby_doctor_recommendations(location_query, risk_level, limit=5):
    cleaned_location = location_query.strip()
    search_focus = get_provider_search_focus(risk_level)
    fallback_links = build_fallback_provider_links(cleaned_location, search_focus) if cleaned_location else []

    if not cleaned_location:
        return {
            "location_name": "",
            "providers": [],
            "fallback_links": [],
            "error": "Enter a city, area, or pincode to get nearby doctor suggestions.",
        }

    try:
        search_params = urlencode(
            {
                "q": cleaned_location,
                "format": "jsonv2",
                "limit": 1,
            }
        )
        geocode_request = Request(
            f"{NOMINATIM_SEARCH_URL}?{search_params}",
            headers={"User-Agent": APP_USER_AGENT},
        )
        with urlopen(geocode_request, timeout=12) as response:
            geocode_results = json.loads(response.read().decode("utf-8"))

        if not geocode_results:
            return {
                "location_name": cleaned_location,
                "providers": [],
                "fallback_links": fallback_links,
                "error": "Location could not be matched precisely, so showing quick search links instead.",
            }

        place = geocode_results[0]
        base_lat = float(place["lat"])
        base_lon = float(place["lon"])
        resolved_name = place.get("display_name", cleaned_location)

        overpass_query = f"""
        [out:json][timeout:25];
        (
          node(around:{DOCTOR_SEARCH_RADIUS_METERS},{base_lat},{base_lon})["amenity"~"hospital|clinic|doctors"];
          way(around:{DOCTOR_SEARCH_RADIUS_METERS},{base_lat},{base_lon})["amenity"~"hospital|clinic|doctors"];
          relation(around:{DOCTOR_SEARCH_RADIUS_METERS},{base_lat},{base_lon})["amenity"~"hospital|clinic|doctors"];
          node(around:{DOCTOR_SEARCH_RADIUS_METERS},{base_lat},{base_lon})["healthcare"~"doctor|clinic|hospital"];
          way(around:{DOCTOR_SEARCH_RADIUS_METERS},{base_lat},{base_lon})["healthcare"~"doctor|clinic|hospital"];
          relation(around:{DOCTOR_SEARCH_RADIUS_METERS},{base_lat},{base_lon})["healthcare"~"doctor|clinic|hospital"];
        );
        out center tags;
        """

        overpass_request = Request(
            OVERPASS_SEARCH_URL,
            data=overpass_query.encode("utf-8"),
            headers={
                "User-Agent": APP_USER_AGENT,
                "Content-Type": "text/plain; charset=utf-8",
            },
        )
        with urlopen(overpass_request, timeout=25) as response:
            overpass_payload = json.loads(response.read().decode("utf-8"))

        providers = []
        seen_entries = set()
        for element in overpass_payload.get("elements", []):
            tags = element.get("tags", {})
            provider_name = tags.get("name") or tags.get("operator") or tags.get("brand")
            if not provider_name:
                continue

            provider_lat = element.get("lat")
            provider_lon = element.get("lon")
            if provider_lat is None or provider_lon is None:
                provider_center = element.get("center", {})
                provider_lat = provider_center.get("lat")
                provider_lon = provider_center.get("lon")
            if provider_lat is None or provider_lon is None:
                continue

            address = format_provider_address(tags)
            unique_key = (provider_name.strip().lower(), address.strip().lower())
            if unique_key in seen_entries:
                continue
            seen_entries.add(unique_key)

            distance_km = calculate_distance_km(base_lat, base_lon, float(provider_lat), float(provider_lon))
            provider_type = get_provider_type_label(tags, provider_name)
            providers.append(
                {
                    "name": provider_name,
                    "provider_type": provider_type,
                    "address": address,
                    "distance_km": round(distance_km, 1),
                    "priority": get_provider_priority(tags, provider_name),
                    "maps_url": build_maps_search_url(f"{provider_name} {resolved_name}"),
                }
            )

        providers.sort(key=lambda item: (-item["priority"], item["distance_km"], item["name"].lower()))
        top_providers = providers[:limit]

        if not top_providers:
            return {
                "location_name": resolved_name,
                "providers": [],
                "fallback_links": fallback_links,
                "error": "No nearby providers were found from the live map lookup, so quick search links are shown instead.",
            }

        return {
            "location_name": resolved_name,
            "providers": top_providers,
            "fallback_links": fallback_links,
            "error": None,
        }
    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError):
        return {
            "location_name": cleaned_location,
            "providers": [],
            "fallback_links": fallback_links,
            "error": "Live nearby doctor lookup is temporarily unavailable, so quick search links are shown instead.",
        }


def render_nearby_doctors_section(location_query, risk_level):
    st.markdown("### Nearby Doctors")
    if not location_query.strip():
        st.info("Enter your city, area, or pincode in the sidebar to see nearby doctor suggestions.")
        return

    doctor_results = get_nearby_doctor_recommendations(location_query, risk_level)
    if doctor_results.get("error"):
        st.caption(doctor_results["error"])
    if doctor_results.get("location_name"):
        st.caption(f"Search location: {doctor_results['location_name']}")

    providers = doctor_results.get("providers", [])
    if providers:
        for provider in providers:
            safe_name = html.escape(provider["name"])
            safe_type = html.escape(provider["provider_type"])
            safe_address = html.escape(provider["address"])
            safe_maps_url = html.escape(provider["maps_url"], quote=True)
            st.markdown(
                f"""
                <div class="panel-card">
                    <div class="panel-title">{safe_name}</div>
                    <div class="panel-text">
                        {safe_type} • {provider['distance_km']:.1f} km away<br>
                        {safe_address}<br>
                        <a href="{safe_maps_url}" target="_blank">Open in Maps</a>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
    else:
        for link in doctor_results.get("fallback_links", []):
            st.markdown(
                f"[{html.escape(link['title'])}]({link['maps_url']})",
                unsafe_allow_html=False,
            )


def build_structured_todo_items(latest_assessment, latest_symptom_assessment, session_history, location_query):
    todo_items = []

    def add_item(priority, workstream, task, outcome, owner):
        todo_items.append(
            {
                "Priority": priority,
                "Workstream": workstream,
                "Task": task,
                "Expected Outcome": outcome,
                "Suggested Owner": owner,
            }
        )

    if latest_assessment:
        risk_band = latest_assessment.get("risk_band", "Low")
        tests = latest_assessment.get("recommended_tests", [])
        care_priority = latest_assessment.get("care_priority", "Routine follow-up")
        add_item(
            "P0" if risk_band == "High" else "P1",
            "Clinical Triage",
            f"Review the latest {risk_band.lower()}-risk prediction and validate the handoff summary.",
            f"Moves the case into a {care_priority.lower()} flow with faster clinician review.",
            "Clinician + Product Lead",
        )
        if tests:
            add_item(
                "P1",
                "Diagnostics",
                f"Schedule or surface the recommended tests: {', '.join(tests[:4])}.",
                "Turns model output into a concrete diagnostic next-step plan.",
                "Care Coordinator",
            )
        add_item(
            "P1",
            "Experience",
            "Keep PDF export, snapshot CSV, and benchmark view aligned with the same risk explanation.",
            "Improves trust, consistency, and demo readiness across outputs.",
            "AI Engineer",
        )

    if latest_symptom_assessment:
        symptom_risk = latest_symptom_assessment.get("risk_level", "Low")
        add_item(
            "P0" if symptom_risk == "High" else "P1",
            "Pre-Screening",
            f"Compare symptom-only {symptom_risk.lower()} risk with ML prediction to flag agreement or mismatch.",
            "Strengthens screening reliability before the user reaches testing or doctor referral.",
            "AI Engineer",
        )
        if latest_symptom_assessment.get("recommended_tests"):
            add_item(
                "P1",
                "Care Guidance",
                "Keep symptom-based recommended tests visible alongside model-based test suggestions.",
                "Gives users a clearer bridge from symptoms to medical action.",
                "Product Designer",
            )

    latest_xray_assessment = st.session_state.get("latest_xray_assessment")
    if latest_xray_assessment:
        xray_risk = latest_xray_assessment.get("risk_band", "Unavailable")
        finding_label = latest_xray_assessment.get("finding_label", "X-ray screening result")
        xray_priority = "P0" if xray_risk == "High" else "P1"
        add_item(
            xray_priority,
            "Imaging Review",
            f"Review the latest chest X-ray screening result: {finding_label}.",
            "Makes sure image-based screening is reflected in the follow-up workflow and clinician review path.",
            "Clinician + AI Engineer",
        )
        if latest_xray_assessment.get("prediction_available"):
            add_item(
                "P1",
                "Workflow",
                f"Cross-check the X-ray {xray_risk.lower()}-risk result against symptoms and structured prediction outputs.",
                "Improves confidence when multiple screening modules agree and highlights mismatches faster.",
                "Care Coordinator",
            )

    if location_query.strip():
        add_item(
            "P1",
            "Care Navigation",
            f"Show nearby doctors and hospitals for {location_query.strip()} with fallback map search links.",
            "Helps users move directly from risk insight to local care access.",
            "Full-Stack Engineer",
        )

    if session_history:
        add_item(
            "P2",
            "Execution Hub",
            "Analyze assessment history trends to identify high-risk clusters and frequent test recommendations.",
            "Turns the execution hub into an operations dashboard, not just a log.",
            "Data Analyst",
        )

    if not todo_items:
        add_item(
            "P0",
            "Setup",
            "Run one symptom check and one ML prediction to activate project intelligence across the workspace.",
            "Unlocks live examples for the AI to-do engine, onboarding plan, and deep-search prompts.",
            "Project Owner",
        )
        add_item(
            "P1",
            "Experience",
            "Add your location in Care Navigator so doctor referral suggestions can be included in the workflow.",
            "Connects screening output with real-world care discovery.",
            "Project Owner",
        )

    priority_rank = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    todo_items.sort(key=lambda item: (priority_rank.get(item["Priority"], 9), item["Workstream"], item["Task"]))
    return todo_items


def build_continuation_grant_bundle(
    pilot_partner,
    deployment_region,
    target_group,
    funding_goal,
    latest_assessment,
    latest_symptom_assessment,
    session_history,
):
    latest_risk = latest_assessment.get("risk_band") if latest_assessment else "Not yet generated"
    latest_symptom_risk = latest_symptom_assessment.get("risk_level") if latest_symptom_assessment else "Not yet generated"
    total_runs = len(session_history)
    high_risk_count = sum(1 for item in session_history if item.get("Risk Band") == "High")

    mission = (
        f"CardioInsight AI is a screening and care-navigation platform for {target_group.lower()} in {deployment_region}. "
        "It combines ML-based heart risk prediction, symptom-based pre-screening, recommended tests, nearby doctor discovery, "
        "Execution Project Hub tracking, and iNSIGHTS support in one workflow."
    )

    funding_use = [
        "Expand validation with more representative cardiovascular data and pilot feedback.",
        "Strengthen onboarding for patients, clinicians, and demo partners with guided setup flows.",
        "Improve local referral quality so risk outputs connect directly to doctors and diagnostic centers.",
        "Add deeper monitoring analytics inside the Execution Project Hub for pilot reporting.",
    ]

    onboarding_steps = [
        f"Introduce {pilot_partner} to the product value story and explain how screening plus referral works.",
        "Create user accounts and confirm location input so nearby care navigation is ready on day one.",
        "Run a symptom-only demo, then a full ML prediction demo, and compare the outputs together.",
        "Export PDF and CSV outputs so clinicians or mentors can review the workflow immediately.",
        "Track pilot usage, high-risk counts, and recommended tests in the Execution Project Hub every week.",
    ]

    success_metrics = [
        f"Pilot activation with {pilot_partner} and a repeatable workflow in {deployment_region}.",
        f"At least {funding_goal.lower()} worth of product progress translated into measurable pilot milestones.",
        "Faster user understanding of what tests to take and where to go next.",
        "Higher trust through consistent symptom screening, ML prediction, and clinician handoff output.",
        f"Live screening evidence: {total_runs} total runs captured so far with {high_risk_count} high-risk flags in session history.",
    ]

    continuation_story = (
        f"The current workspace already supports prediction, symptom triage, recommended tests, local care navigation, "
        f"Execution Project Hub tracking, and iNSIGHTS integration. The next funding phase would help turn this from a strong "
        f"demo into a pilot-ready healthcare product. Current internal signals show ML risk at '{latest_risk}' and symptom risk at "
        f"'{latest_symptom_risk}', which demonstrates how the platform can triangulate care guidance instead of relying on a single view."
    )

    return {
        "mission": mission,
        "continuation_story": continuation_story,
        "funding_use": funding_use,
        "onboarding_steps": onboarding_steps,
        "success_metrics": success_metrics,
    }


def build_product_deep_search_bundle(search_goal, user_segment, deployment_region):
    goal_context = {
        "Clinical Adoption": {
            "problem": "How do we make clinicians trust and adopt AI-assisted cardiovascular pre-screening in real workflows?",
            "sources": ["Hospital innovation case studies", "Clinical AI validation papers", "Digital health workflow research"],
        },
        "User Retention": {
            "problem": "What makes patients return to a preventive heart-health assistant instead of using it only once?",
            "sources": ["Patient engagement studies", "Preventive care retention benchmarks", "Behavior change design research"],
        },
        "Diagnostic Partnerships": {
            "problem": "How can the product connect screening output with labs, diagnostic centers, and cardiology referrals?",
            "sources": ["Diagnostic network models", "Referral workflow studies", "Health operations partnerships"],
        },
        "Healthcare AI Safety": {
            "problem": "How should the product communicate risk, uncertainty, and escalation so users are guided safely?",
            "sources": ["AI safety in healthcare", "Risk communication guidelines", "Triage UX research"],
        },
    }.get(
        search_goal,
        {
            "problem": "What is the highest-value path to turn this heart screening product into a scalable care workflow?",
            "sources": ["Health product strategy research", "Clinical workflow transformation", "Digital triage case studies"],
        },
    )

    search_queries = [
        f"{search_goal.lower()} for AI heart screening products in {deployment_region}",
        f"{user_segment.lower()} adoption barriers for cardiovascular digital health tools",
        f"best practices for symptom checker plus ML prediction workflows in healthcare",
        f"cardiology referral experience design for preventive screening platforms in {deployment_region}",
        f"digital health trust signals for {user_segment.lower()} using AI-assisted risk tools",
    ]

    deep_questions = [
        "What makes users trust a screening result enough to take the next clinical action?",
        "Where do symptom-based guidance and model-based guidance disagree, and how should that be explained?",
        "Which diagnostic tests create the highest confidence gain after a medium-risk or high-risk result?",
        f"What would make {user_segment.lower()} recommend this workflow to peers or clinicians?",
        f"What regulatory, operational, or partnership blockers matter most in {deployment_region}?",
    ]

    experiment_tracks = [
        "Prototype a guided path from risk result to recommended tests to nearby doctor selection.",
        "Compare onboarding completion with and without a step-by-step care navigator.",
        "Measure whether clinicians prefer summary cards, PDF handoffs, or execution hub exports.",
        "Test whether symptom checker results improve trust before a full ML assessment.",
    ]

    return {
        "problem_statement": goal_context["problem"],
        "recommended_sources": goal_context["sources"],
        "search_queries": search_queries,
        "deep_questions": deep_questions,
        "experiment_tracks": experiment_tracks,
    }


def initialize_app_state():
    if "patient_id" not in st.session_state:
        st.session_state.patient_id = generate_patient_id()
    if "assessment_history" not in st.session_state:
        st.session_state.assessment_history = []
    if "latest_assessment" not in st.session_state:
        st.session_state.latest_assessment = None
    if "latest_xray_assessment" not in st.session_state:
        st.session_state.latest_xray_assessment = None
    if "latest_symptom_assessment" not in st.session_state:
        st.session_state.latest_symptom_assessment = None
    if "care_location_query" not in st.session_state:
        st.session_state.care_location_query = ""


def get_selected_symptom_labels(symptoms):
    return [label for key, label, _ in SYMPTOM_FIELDS if symptoms.get(key)]


def get_symptom_risk_result(symptoms):
    selected_labels = get_selected_symptom_labels(symptoms)
    selected_count = len(selected_labels)
    serious_count = sum(1 for key in SERIOUS_SYMPTOMS if symptoms.get(key))
    major_count = sum(1 for key in MAJOR_SYMPTOMS if symptoms.get(key))
    total_score = sum(weight for key, _, weight in SYMPTOM_FIELDS if symptoms.get(key))

    classic_warning_pattern = symptoms.get("chest_pain") and (
        symptoms.get("shortness_of_breath")
        or symptoms.get("pain_left_arm_jaw")
        or symptoms.get("irregular_heartbeat")
        or symptoms.get("sweating")
        or symptoms.get("nausea")
    )

    if classic_warning_pattern or serious_count >= 2 or total_score >= 8:
        risk_level = "High"
        explanation = (
            "Multiple concerning heart-related symptoms are present, which can match a higher-risk pattern "
            "that deserves prompt medical review."
        )
    elif major_count >= 1 or total_score >= 3 or selected_count >= 2:
        risk_level = "Medium"
        explanation = (
            "Some symptoms could be linked to cardiovascular strain, so a structured clinical checkup and "
            "basic heart testing would be sensible."
        )
    else:
        risk_level = "Low"
        explanation = (
            "No strong high-risk symptom cluster was selected. Current symptom pattern looks lower risk, "
            "but ongoing or worsening symptoms should still be discussed with a clinician."
        )

    if not selected_labels:
        explanation = (
            "No symptoms were selected, so the symptom-based pre-screening signal is low at the moment. "
            "Use the full prediction studio for a data-driven assessment."
        )

    return {
        "risk_level": risk_level,
        "explanation": explanation,
        "selected_labels": selected_labels,
        "selected_count": selected_count,
        "serious_count": serious_count,
        "major_count": major_count,
        "total_score": total_score,
    }


def get_recommended_tests_from_symptoms(symptoms, risk_level):
    recommended_tests = []

    def add_test(test_name):
        if test_name not in recommended_tests:
            recommended_tests.append(test_name)

    if symptoms.get("chest_pain") or symptoms.get("irregular_heartbeat") or symptoms.get("shortness_of_breath"):
        add_test("ECG")
    if symptoms.get("dizziness") or symptoms.get("sweating") or symptoms.get("chest_pain"):
        add_test("Blood Pressure test")
    if symptoms.get("fatigue") or symptoms.get("chest_pain") or symptoms.get("pain_left_arm_jaw") or risk_level in {"Medium", "High"}:
        add_test("Cholesterol test")
    if (
        symptoms.get("chest_pain")
        or symptoms.get("shortness_of_breath")
        or symptoms.get("fatigue")
        or symptoms.get("pain_left_arm_jaw")
    ) and risk_level in {"Medium", "High"}:
        add_test("Stress test")
    if symptoms.get("irregular_heartbeat") or symptoms.get("shortness_of_breath") or symptoms.get("dizziness") or risk_level == "High":
        add_test("Echocardiogram")

    if not recommended_tests and risk_level == "Low":
        add_test("Blood Pressure test")

    return recommended_tests


def get_symptom_guidance(risk_level):
    if risk_level == "High":
        return [
            "Consult a doctor or cardiologist as soon as possible, especially if symptoms are active now.",
            "Avoid heavy physical exertion until you are medically evaluated.",
            "Use the full prediction studio and share both results with a clinician for faster triage.",
        ]
    if risk_level == "Medium":
        return [
            "Book a medical checkup and complete the recommended tests in the near term.",
            "Track when symptoms happen, how long they last, and what triggers them.",
            "Support heart health with lower-sodium meals, regular sleep, hydration, and smoking avoidance.",
        ]
    return [
        "Current symptom pattern looks lower risk, but monitor for new chest pain, breathlessness, or palpitations.",
        "Stay consistent with exercise, balanced diet, hydration, and routine preventive health checks.",
        "If symptoms persist or become stronger, step up to a clinician review even if this screen is low risk.",
    ]


def get_risk_band_from_probability(risk_probability):
    normalized_probability = max(0.0, min(float(risk_probability or 0.0), 1.0))
    if normalized_probability < LOW_RISK_MAX:
        return "Low"
    if normalized_probability < MEDIUM_RISK_MAX:
        return "Medium"
    return "High"


def get_risk_band(risk_probability, prediction, disease_class):
    if risk_probability is None:
        return "High" if prediction == disease_class else "Low"
    return get_risk_band_from_probability(risk_probability)


def get_risk_result_text(risk_band):
    return f"{risk_band} risk of heart disease detected."


def get_status_class(risk_band):
    return {
        "Low": "status-low",
        "Medium": "status-medium",
        "High": "status-high",
    }.get(risk_band, "status-low")


def get_care_priority(risk_probability, prediction, disease_class):
    if risk_probability is None:
        return "Cardiology review" if prediction == disease_class else "Routine follow-up"
    if risk_probability >= MEDIUM_RISK_MAX:
        return "Priority physician review"
    if risk_probability >= LOW_RISK_MAX:
        return "Structured monitoring plan"
    return "Routine wellness follow-up"


def get_quality_flags(input_data):
    row = input_data.iloc[0]
    flags = []

    if row["trestbps"] >= 180:
        flags.append(("error", "Resting blood pressure is in a severely elevated range and needs prompt review."))
    elif row["trestbps"] >= 140:
        flags.append(("warning", "Resting blood pressure is elevated and should be monitored carefully."))

    if row["chol"] >= 300:
        flags.append(("warning", "Cholesterol is far above the common target range for cardiovascular health."))

    if row["thalach"] < 100:
        flags.append(("warning", "Maximum heart rate achieved is low for this profile and may deserve a functional review."))

    if row["oldpeak"] >= 2.5:
        flags.append(("warning", "Oldpeak is notably elevated, which can strengthen the stress-related risk pattern."))

    if row["ca"] >= 3:
        flags.append(("error", "The major vessel count is strongly aligned with higher-risk cases in the training data."))

    if row["exang"] == 1:
        flags.append(("info", "Exercise-induced angina is marked present, so exertional symptoms should be discussed clinically."))

    if not flags:
        flags.append(("success", "Submitted values are within expected model input ranges and no urgent outlier flag was triggered."))

    return flags


def build_benchmark_table(input_data, reference_df, class_profiles, disease_class, healthy_class):
    if reference_df.empty:
        return pd.DataFrame()

    row = input_data.iloc[0]
    benchmark_rows = []

    for feature in BENCHMARK_FEATURES:
        if feature not in reference_df.columns:
            continue

        series = pd.to_numeric(reference_df[feature], errors="coerce").dropna()
        if series.empty:
            continue

        value = float(row[feature])
        percentile = round(float((series <= value).mean() * 100), 1)
        healthy_average = class_profiles.get(healthy_class, {}).get(feature)
        disease_average = class_profiles.get(disease_class, {}).get(feature)

        benchmark_rows.append(
            {
                "Measure": FEATURE_LABELS.get(feature, feature),
                "Patient": format_feature_value(feature, value),
                "Dataset Percentile": f"{percentile:.1f}th",
                "Healthy Avg": format_feature_value(feature, healthy_average) if healthy_average is not None else "N/A",
                "High-Risk Avg": format_feature_value(feature, disease_average) if disease_average is not None else "N/A",
            }
        )

    return pd.DataFrame(benchmark_rows)


def build_handoff_summary(patient_name, patient_id, doctor_name, prediction_text, risk_band, care_priority, insights):
    insight_text = " ".join(insights[:2]) if insights else "The model used the combined cardiovascular pattern."
    return (
        f"{patient_name} ({patient_id}) was screened under {doctor_name} and the model outcome was: {prediction_text} "
        f"The case is currently tagged as {risk_band.lower()} risk with a recommended priority of {care_priority.lower()}. "
        f"{insight_text}"
    )


def build_assessment_record(
    patient_name,
    patient_id,
    doctor_name,
    prediction_text,
    risk_probability,
    risk_band,
    care_priority,
    model_name,
):
    return {
        "Assessment Time": datetime.now().strftime("%d %b %Y, %I:%M %p"),
        "Patient Name": patient_name,
        "Patient ID": patient_id,
        "Doctor": doctor_name,
        "Model": model_name,
        "Risk Score (%)": round(float((risk_probability or 0) * 100), 2),
        "Risk Band": risk_band,
        "Care Priority": care_priority,
        "Outcome": prediction_text,
    }


def get_xray_care_priority(risk_band, prediction_available):
    if not prediction_available:
        return "Model setup required"
    if risk_band == "High":
        return "Priority physician review"
    if risk_band == "Medium":
        return "Structured monitoring plan"
    return "Routine follow-up"


def build_report_rows(input_data):
    row = input_data.iloc[0]
    return [
        ("Age", format_feature_value("age", row["age"])),
        ("Gender", format_feature_value("sex", row["sex"])),
        ("Chest Pain Type", format_feature_value("cp", row["cp"])),
        ("Resting Blood Pressure", f"{int(row['trestbps'])} mm Hg"),
        ("Cholesterol", f"{int(row['chol'])} mg/dl"),
        ("Fasting Blood Sugar > 120", format_feature_value("fbs", row["fbs"])),
        ("Resting ECG", format_feature_value("restecg", row["restecg"])),
        ("Maximum Heart Rate", format_feature_value("thalach", row["thalach"])),
        ("Exercise Induced Angina", format_feature_value("exang", row["exang"])),
        ("Oldpeak", format_feature_value("oldpeak", row["oldpeak"])),
        ("Slope", format_feature_value("slope", row["slope"])),
        ("Major Vessels", format_feature_value("ca", row["ca"])),
        ("Thal", format_feature_value("thal", row["thal"])),
    ]


PDF_PAGE_WIDTH = 210
PDF_MARGIN_X = 12
PDF_CONTENT_WIDTH = PDF_PAGE_WIDTH - (PDF_MARGIN_X * 2)


def pdf_safe(value):
    return str(value).encode("latin-1", "replace").decode("latin-1")


def get_pdf_theme(risk_band):
    themes = {
        "High": {
            "primary": (185, 28, 28),
            "soft": (254, 242, 242),
            "border": (254, 205, 211),
        },
        "Medium": {
            "primary": (180, 83, 9),
            "soft": (255, 247, 237),
            "border": (253, 230, 138),
        },
        "Low": {
            "primary": (15, 118, 110),
            "soft": (240, 253, 250),
            "border": (153, 246, 228),
        },
    }
    base_theme = themes.get(risk_band, themes["Low"])
    base_theme.update(
        {
            "ink": (15, 23, 42),
            "muted": (71, 85, 105),
            "line": (203, 213, 225),
            "card": (248, 250, 252),
            "header": (15, 23, 42),
        }
    )
    return base_theme


class StyledReportPDF(FPDF):
    def __init__(self, theme):
        super().__init__()
        self.theme = theme
        self.alias_nb_pages()
        self.set_auto_page_break(auto=True, margin=18)

    def header(self):
        self.set_fill_color(*self.theme["header"])
        self.rect(0, 0, PDF_PAGE_WIDTH, 24, "F")
        self.set_fill_color(*self.theme["primary"])
        self.rect(0, 24, PDF_PAGE_WIDTH, 2.2, "F")
        self.set_text_color(255, 255, 255)
        self.set_font("Arial", "B", 16)
        self.set_xy(PDF_MARGIN_X, 7)
        self.cell(0, 6, pdf_safe(HOSPITAL_NAME))
        self.set_xy(PDF_MARGIN_X, 13.5)
        self.set_font("Arial", size=8.5)
        self.cell(0, 4, pdf_safe(f"{HOSPITAL_ADDRESS} | {HOSPITAL_CONTACT}"))
        self.ln(12)

    def footer(self):
        self.set_y(-14)
        self.set_draw_color(*self.theme["line"])
        self.line(PDF_MARGIN_X, self.get_y(), PDF_PAGE_WIDTH - PDF_MARGIN_X, self.get_y())
        self.ln(2.5)
        self.set_font("Arial", size=8)
        self.set_text_color(*self.theme["muted"])
        self.set_x(PDF_MARGIN_X)
        self.cell(
            120,
            4,
            pdf_safe("Confidential clinical screening document - AI-assisted summary."),
        )
        self.cell(
            PDF_CONTENT_WIDTH - 120,
            4,
            pdf_safe(f"Page {self.page_no()}/{{nb}}"),
            align="R",
        )


def ensure_pdf_space(pdf, height):
    if pdf.get_y() + height > 276:
        pdf.add_page()


def add_pdf_section_header(pdf, title, subtitle=None):
    box_height = 12 if not subtitle else 16
    ensure_pdf_space(pdf, box_height + 4)
    y = pdf.get_y()
    pdf.set_fill_color(*pdf.theme["soft"])
    pdf.set_draw_color(*pdf.theme["border"])
    pdf.rect(PDF_MARGIN_X, y, PDF_CONTENT_WIDTH, box_height, "DF")
    pdf.set_fill_color(*pdf.theme["primary"])
    pdf.rect(PDF_MARGIN_X, y, 4, box_height, "F")
    pdf.set_text_color(*pdf.theme["ink"])
    pdf.set_xy(PDF_MARGIN_X + 8, y + 2.3)
    pdf.set_font("Arial", "B", 11)
    pdf.cell(0, 5, pdf_safe(title))
    if subtitle:
        pdf.set_xy(PDF_MARGIN_X + 8, y + 7.5)
        pdf.set_text_color(*pdf.theme["muted"])
        pdf.set_font("Arial", size=8.5)
        pdf.cell(0, 4, pdf_safe(subtitle))
    pdf.set_y(y + box_height + 3)


def add_metric_cards(pdf, cards):
    card_width = 58
    card_height = 22
    gap = 6
    start_x = PDF_MARGIN_X
    y = pdf.get_y()
    ensure_pdf_space(pdf, card_height + 5)

    for index, (title, value) in enumerate(cards):
        x = start_x + index * (card_width + gap)
        pdf.set_fill_color(255, 255, 255)
        pdf.set_draw_color(*pdf.theme["line"])
        pdf.rect(x, y, card_width, card_height, "DF")
        pdf.set_fill_color(*pdf.theme["primary"])
        pdf.rect(x, y, 4, card_height, "F")
        pdf.set_xy(x + 7, y + 3)
        pdf.set_text_color(*pdf.theme["muted"])
        pdf.set_font("Arial", size=8.5)
        pdf.cell(card_width - 10, 4, pdf_safe(title))
        pdf.set_xy(x + 7, y + 9)
        pdf.set_text_color(*pdf.theme["ink"])
        pdf.set_font("Arial", "B", 11)
        pdf.multi_cell(card_width - 10, 5, pdf_safe(value))

    pdf.set_y(y + card_height + 4)


def add_key_value_table(pdf, rows):
    label_width = 27
    value_width = 66
    row_height = 8
    shade = False

    for index in range(0, len(rows), 2):
        ensure_pdf_space(pdf, row_height + 1)
        left_pair = rows[index]
        right_pair = rows[index + 1] if index + 1 < len(rows) else ("", "")
        fill_color = pdf.theme["card"] if shade else (255, 255, 255)
        pdf.set_fill_color(*fill_color)
        pdf.set_draw_color(*pdf.theme["line"])
        pdf.set_text_color(*pdf.theme["ink"])
        pdf.set_font("Arial", "B", 9.5)
        pdf.cell(label_width, row_height, pdf_safe(left_pair[0]), border=1, fill=True)
        pdf.set_font("Arial", size=9.5)
        pdf.cell(value_width, row_height, pdf_safe(left_pair[1]), border=1, fill=True)
        pdf.set_font("Arial", "B", 9.5)
        pdf.cell(label_width, row_height, pdf_safe(right_pair[0]), border=1, fill=True)
        pdf.set_font("Arial", size=9.5)
        pdf.cell(value_width, row_height, pdf_safe(right_pair[1]), border=1, ln=1, fill=True)
        shade = not shade


def add_clinical_parameters_table(pdf, report_rows):
    label_width = 74
    value_width = PDF_CONTENT_WIDTH - label_width
    row_height = 8
    shade = False

    pdf.set_fill_color(*pdf.theme["primary"])
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Arial", "B", 10)
    pdf.cell(label_width, row_height, "Clinical Parameter", border=1, fill=True)
    pdf.cell(value_width, row_height, "Observed Value", border=1, ln=1, fill=True)

    for label, value in report_rows:
        ensure_pdf_space(pdf, row_height + 1)
        fill_color = pdf.theme["card"] if shade else (255, 255, 255)
        pdf.set_fill_color(*fill_color)
        pdf.set_text_color(*pdf.theme["ink"])
        pdf.set_font("Arial", "B", 9.5)
        pdf.cell(label_width, row_height, pdf_safe(label), border=1, fill=True)
        pdf.set_font("Arial", size=9.5)
        pdf.cell(value_width, row_height, pdf_safe(value), border=1, ln=1, fill=True)
        shade = not shade


def add_bullet_list(pdf, items):
    if not items:
        items = ["No additional items were generated for this section."]

    for item in items:
        ensure_pdf_space(pdf, 8)
        y = pdf.get_y()
        pdf.set_fill_color(*pdf.theme["primary"])
        pdf.rect(PDF_MARGIN_X + 1.5, y + 2.2, 2.2, 2.2, "F")
        pdf.set_xy(PDF_MARGIN_X + 6, y)
        pdf.set_text_color(*pdf.theme["ink"])
        pdf.set_font("Arial", size=10)
        pdf.multi_cell(PDF_CONTENT_WIDTH - 8, 6, pdf_safe(item))
        pdf.ln(0.6)


def add_text_panel(pdf, text, fill_color):
    ensure_pdf_space(pdf, 18)
    pdf.set_fill_color(*fill_color)
    pdf.set_draw_color(*pdf.theme["line"])
    x = PDF_MARGIN_X
    y = pdf.get_y()
    pdf.rect(x, y, PDF_CONTENT_WIDTH, 18, "DF")
    pdf.set_xy(x + 4, y + 3)
    pdf.set_text_color(*pdf.theme["ink"])
    pdf.set_font("Arial", size=10)
    pdf.multi_cell(PDF_CONTENT_WIDTH - 8, 5.5, pdf_safe(text))
    pdf.set_y(max(pdf.get_y(), y + 18) + 2)


def generate_report_pdf(
    patient_name,
    patient_id,
    doctor_name,
    report_datetime,
    result_text,
    risk_probability,
    risk_band,
    care_priority,
    input_data,
    insights,
    suggestions,
    handoff_summary,
    recommended_tests=None,
    quality_flags=None,
    model_name="Heart disease classifier",
):
    theme = get_pdf_theme(risk_band)
    pdf = StyledReportPDF(theme)
    pdf.add_page()
    risk_score = f"{risk_probability * 100:.2f}%" if risk_probability is not None else "Not available"
    report_rows = build_report_rows(input_data)
    quality_messages = [f"{level.title()}: {message}" for level, message in (quality_flags or [])]

    pdf.set_fill_color(255, 255, 255)
    pdf.set_draw_color(*theme["line"])
    intro_y = pdf.get_y() + 4
    pdf.rect(PDF_MARGIN_X, intro_y, PDF_CONTENT_WIDTH, 26, "DF")
    pdf.set_fill_color(*theme["primary"])
    pdf.rect(PDF_MARGIN_X, intro_y, 5, 26, "F")
    pdf.set_xy(PDF_MARGIN_X + 9, intro_y + 4)
    pdf.set_text_color(*theme["ink"])
    pdf.set_font("Arial", "B", 16)
    pdf.cell(116, 6, "Heart Disease AI Screening Report")
    badge_width = 36
    badge_x = PDF_MARGIN_X + PDF_CONTENT_WIDTH - badge_width - 8
    badge_y = intro_y + 6
    pdf.set_fill_color(*theme["primary"])
    pdf.rect(badge_x, badge_y, badge_width, 10, "F")
    pdf.set_xy(badge_x, badge_y + 2.2)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Arial", "B", 10)
    pdf.cell(badge_width, 5, pdf_safe(f"{risk_band} RISK"), align="C")
    pdf.set_xy(PDF_MARGIN_X + 9, intro_y + 12)
    pdf.set_text_color(*theme["muted"])
    pdf.set_font("Arial", size=9.5)
    pdf.multi_cell(
        122,
        5,
        pdf_safe(
            "AI-assisted cardiovascular screening summary prepared for clinician review and patient follow-up planning."
        ),
    )
    pdf.set_y(intro_y + 31)

    add_metric_cards(
        pdf,
        [
            ("Screening Result", result_text),
            ("Estimated Risk", risk_score),
            ("Care Priority", care_priority),
        ],
    )

    add_pdf_section_header(pdf, "Patient And Visit Details", "Core identity and reporting information")
    add_key_value_table(
        pdf,
        [
            ("Patient Name", patient_name),
            ("Patient ID", patient_id),
            ("Consulting Doctor", doctor_name),
            ("Report Date", report_datetime),
            ("Risk Band", risk_band),
            ("Model", model_name),
        ],
    )
    pdf.ln(4)

    add_pdf_section_header(pdf, "Clinical Parameters", "Submitted measurements used by the model")
    add_clinical_parameters_table(pdf, report_rows)
    pdf.ln(4)

    add_pdf_section_header(pdf, "Why The Model Flagged This Case", "Most relevant risk-shaping observations")
    add_bullet_list(pdf, insights[:4])
    pdf.ln(2)

    add_pdf_section_header(pdf, "Recommended Next Steps", "Patient-facing guidance after this screening")
    add_bullet_list(pdf, suggestions[:5])
    pdf.ln(2)

    if recommended_tests:
        add_pdf_section_header(pdf, "Recommended Tests", "Suggested diagnostic follow-up items")
        add_bullet_list(pdf, recommended_tests[:5])
        pdf.ln(2)

    add_pdf_section_header(pdf, "Quality Review", "Measurement flags and notable data checks")
    add_bullet_list(pdf, quality_messages[:5])
    pdf.ln(2)

    add_pdf_section_header(pdf, "Clinical Note")
    add_text_panel(
        pdf,
        "This report is an AI-assisted screening summary generated from the submitted clinical values. "
        "It should support, not replace, professional medical diagnosis.",
        theme["card"],
    )

    add_pdf_section_header(pdf, "Clinician Handoff Summary")
    add_text_panel(pdf, handoff_summary, theme["soft"])

    ensure_pdf_space(pdf, 18)
    pdf.set_text_color(*theme["ink"])
    pdf.set_font("Arial", "B", 10.5)
    pdf.cell(0, 6, "Authorized By: ____________________", ln=1)
    pdf.set_font("Arial", size=10)
    pdf.cell(0, 6, "Department: Cardiology", ln=1)

    return pdf.output(dest="S").encode("latin-1")

st.set_page_config(page_title="CardioInsight AI", page_icon="H", layout="wide")
inject_css()
initialize_auth_db()
initialize_auth_state()

if not st.session_state.auth_user:
    render_auth_screen()
    st.stop()

st.markdown(
    """
    <div class="hero-card">
        <div class="hero-eyebrow">Hackathon Ready Healthcare AI</div>
        <div class="hero-title">CardioInsight AI</div>
        <div class="hero-subtitle">
            A heart disease prediction workspace with calibrated risk scoring, model-backed explanation,
            clinician handoff summary, Execution Project Hub analytics, downloadable hospital reporting,
            and an integrated iNSIGHTS experience.
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

try:
    bundle = load_model_bundle()
except FileNotFoundError as error:
    st.error(str(error))
    st.stop()

model = bundle["model"]
disease_class = bundle["disease_class"]
healthy_class = bundle["healthy_class"]
metrics = bundle.get("metrics", {})
feature_importance = bundle.get("feature_importance", {})
dataset_summary = bundle.get("dataset_summary", {})
model_path, model_mtime, model_size = get_xray_model_signature()
xray_bundle = load_xray_model_bundle(model_path, model_mtime, model_size)
reference_df = load_reference_data()
initialize_app_state()

with st.sidebar:
    auth_user = st.session_state.auth_user
    safe_full_name = html.escape(auth_user["full_name"])
    safe_email = html.escape(auth_user["email"])
    st.markdown(
        f"""
        <div class="auth-user-card">
            <div class="auth-user-title">Signed In</div>
            <div class="auth-user-name">{safe_full_name}</div>
            <div class="auth-user-email">{safe_email}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("Logout", use_container_width=True):
        logout_user()
        st.rerun()
    st.markdown("---")
    st.header("Model Snapshot")
    st.write(f"Model: `{bundle.get('model_name', type(model).__name__)}`")
    if metrics.get("accuracy") is not None:
        st.write(f"Test accuracy: `{metrics['accuracy'] * 100:.2f}%`")
    if metrics.get("macro_f1") is not None:
        st.write(f"Macro F1: `{metrics['macro_f1'] * 100:.2f}%`")
    for step in bundle.get("preprocessing", []):
        st.markdown(f"- {step}")
    st.markdown("---")
    st.subheader("iNSIGHTS")
    st.write("Launch the attached iNSIGHTS experience from here.")
    st.link_button("Open iNSIGHTS", INSIGHTS_PUBLIC_URL)
    st.markdown("---")
    st.subheader("Execution Project Hub")
    session_history = st.session_state.get("assessment_history", [])
    high_risk_count = sum(1 for item in session_history if item.get("Risk Band") == "High")
    hub_col1, hub_col2 = st.columns(2)
    with hub_col1:
        st.metric("Runs", len(session_history))
    with hub_col2:
        st.metric("High Risk", high_risk_count)
    if st.button("Generate New Patient ID", use_container_width=True):
        st.session_state.patient_id = generate_patient_id()
        st.rerun()
    if session_history and st.button("Clear Session Hub", use_container_width=True):
        st.session_state.assessment_history = []
        st.session_state.latest_assessment = None
        st.session_state.latest_xray_assessment = None
        st.rerun()
    st.markdown("---")
    st.subheader("Care Navigator")
    st.caption("Used for nearby doctor suggestions in both risk modules.")
    st.text_input(
        "Your location",
        key="care_location_query",
        placeholder="e.g. New Delhi, Saket, or 110017",
    )

predict_tab, xray_tab, symptom_tab, store_tab, chat_tab, hub_tab, model_tab, insights_tab, project_suite_tab = st.tabs(
    [
        "Prediction Studio",
        "X-Ray Screening",
        "Symptom Checker",
        "Patient Store",
        "Health Chat",
        "Execution Project Hub",
        "Model Performance",
        "iNSIGHTS",
        "AI Project Suite",
    ]
)

with predict_tab:
    st.markdown(
        """
        <div class="glass-card">
            <div class="section-title">Patient Intake</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    active_patient_id = st.session_state.patient_id
    with st.form("prediction_form"):
        patient_col1, patient_col2, patient_col3 = st.columns(3)

        with patient_col1:
            patient_name = st.text_input("Patient name", value="Rahul Sharma")
        with patient_col2:
            st.text_input("Patient ID", value=active_patient_id, disabled=True)
        with patient_col3:
            doctor_name = st.text_input("Consulting doctor", value="Dr. A. Mehta")

        st.markdown("### Clinical Inputs")
        col1, col2, col3 = st.columns(3)

        with col1:
            age = st.number_input("Age", min_value=1, max_value=120, value=52, step=1)
            sex = st.selectbox("Gender", options=[0, 1], format_func=lambda x: GENDER_LABELS[x])
            cp = st.selectbox("Chest pain type", options=[0, 1, 2, 3], format_func=lambda x: CP_LABELS[x])
            trestbps = st.number_input("Resting blood pressure", min_value=80, max_value=250, value=125, step=1)
            chol = st.number_input("Cholesterol", min_value=100, max_value=700, value=212, step=1)

        with col2:
            fbs = st.selectbox("Fasting blood sugar > 120 mg/dl", options=[0, 1], format_func=lambda x: YES_NO_LABELS[x])
            restecg = st.selectbox("Resting ECG result", options=[0, 1, 2], format_func=lambda x: RESTECG_LABELS[x])
            thalach = st.number_input("Maximum heart rate achieved", min_value=60, max_value=250, value=168, step=1)
            exang = st.selectbox("Exercise induced angina", options=[0, 1], format_func=lambda x: YES_NO_LABELS[x])
            oldpeak = st.number_input("Oldpeak", min_value=0.0, max_value=10.0, value=1.0, step=0.1, format="%.1f")

        with col3:
            slope = st.selectbox("Slope", options=[0, 1, 2], format_func=lambda x: SLOPE_LABELS[x])
            ca = st.selectbox("Number of major vessels", options=[0, 1, 2, 3, 4], index=2)
            thal = st.selectbox("Thal", options=[0, 1, 2, 3], index=3, format_func=lambda x: THAL_LABELS[x])

        submitted = st.form_submit_button("Analyze Heart Risk")

    current_assessment = st.session_state.get("latest_assessment")
    if submitted:
        input_data = build_input_frame(
            age=age,
            sex=sex,
            cp=cp,
            trestbps=trestbps,
            chol=chol,
            fbs=fbs,
            restecg=restecg,
            thalach=thalach,
            exang=exang,
            oldpeak=oldpeak,
            slope=slope,
            ca=ca,
            thal=thal,
        )

        prediction = int(model.predict(input_data)[0])
        risk_probability = get_risk_probability(model, input_data, disease_class)
        risk_band = get_risk_band(risk_probability, prediction, disease_class)
        prediction_text = get_risk_result_text(risk_band)
        status_class = get_status_class(risk_band)
        risk_percentage = f"{(risk_probability or 0) * 100:.2f}%"

        prediction_insights = get_prediction_insights(input_data, bundle, prediction)
        if not prediction_insights:
            prediction_insights = [
                "The model reviewed the combined pattern of cardiovascular measurements rather than a single field."
            ]

        patient_name_clean = patient_name.strip() or "Unknown Patient"
        doctor_name_clean = doctor_name.strip() or "Not Provided"
        care_priority = get_care_priority(risk_probability, prediction, disease_class)
        patient_suggestions = get_patient_suggestions(input_data, risk_probability)
        recommended_tests = get_recommended_tests_from_prediction(input_data, risk_probability, risk_band)
        quality_flags = get_quality_flags(input_data)
        benchmark_df = build_benchmark_table(
            input_data=input_data,
            reference_df=reference_df,
            class_profiles=bundle.get("class_profiles", {}),
            disease_class=disease_class,
            healthy_class=healthy_class,
        )
        handoff_summary = build_handoff_summary(
            patient_name=patient_name_clean,
            patient_id=active_patient_id,
            doctor_name=doctor_name_clean,
            prediction_text=prediction_text,
            risk_band=risk_band,
            care_priority=care_priority,
            insights=prediction_insights,
        )
        display_snapshot = pd.DataFrame(build_report_rows(input_data), columns=["Parameter", "Value"])

        st.markdown(
            f"""
            <div class="glass-card" style="margin-top: 1rem;">
                <div class="status-pill {status_class}">{prediction_text}</div>
                <div class="section-title">Prediction Dashboard</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        report_pdf = generate_report_pdf(
            patient_name=patient_name_clean,
            patient_id=active_patient_id,
            doctor_name=doctor_name_clean,
            report_datetime=datetime.now().strftime("%d %b %Y, %I:%M %p"),
            result_text=prediction_text,
            risk_probability=risk_probability,
            risk_band=risk_band,
            care_priority=care_priority,
            input_data=input_data,
            insights=prediction_insights,
            suggestions=patient_suggestions,
            handoff_summary=handoff_summary,
            recommended_tests=recommended_tests,
            quality_flags=quality_flags,
            model_name=bundle.get("model_name", type(model).__name__),
        )

        current_assessment = {
            "patient_name": patient_name_clean,
            "patient_id": active_patient_id,
            "doctor_name": doctor_name_clean,
            "prediction_text": prediction_text,
            "status_class": status_class,
            "risk_probability": risk_probability,
            "risk_percentage": risk_percentage,
            "risk_band": risk_band,
            "care_priority": care_priority,
            "insights": prediction_insights,
            "suggestions": patient_suggestions,
            "recommended_tests": recommended_tests,
            "quality_flags": quality_flags,
            "benchmark_df": benchmark_df,
            "display_snapshot": display_snapshot,
            "report_pdf": report_pdf,
            "handoff_summary": handoff_summary,
            "model_name": bundle.get("model_name", type(model).__name__),
        }
        st.session_state.latest_assessment = current_assessment
        st.session_state.assessment_history = [
            build_assessment_record(
                patient_name=patient_name_clean,
                patient_id=active_patient_id,
                doctor_name=doctor_name_clean,
                prediction_text=prediction_text,
                risk_probability=risk_probability,
                risk_band=risk_band,
                care_priority=care_priority,
                model_name=bundle.get("model_name", type(model).__name__),
            ),
            *st.session_state.assessment_history,
        ][:30]

        patient_data = {
            'patient_id': active_patient_id,
            'patient_name': patient_name_clean,
            'doctor_name': doctor_name_clean,
            'timestamp': datetime.now().isoformat(),
            'age': age,
            'sex': sex,
            'cp': cp,
            'trestbps': trestbps,
            'chol': chol,
            'fbs': fbs,
            'restecg': restecg,
            'thalach': thalach,
            'exang': exang,
            'oldpeak': oldpeak,
            'slope': slope,
            'ca': ca,
            'thal': thal,
            'prediction': prediction,
            'risk_probability': risk_probability,
            'risk_band': risk_band,
        }
        save_patient_data(patient_data)
        
        # Store patient data in vectorstore for hindsight learning
        try:
            vectorstore = get_vectorstore()
            # Prepare data for vectorization (excluding non-numeric fields)
            vector_data = {
                'age': age,
                'sex': sex,
                'cp': cp,
                'trestbps': trestbps,
                'chol': chol,
                'fbs': fbs,
                'restecg': restecg,
                'thalach': thalach,
                'exang': exang,
                'oldpeak': oldpeak,
                'slope': slope,
                'ca': ca,
                'thal': thal,
            }
            vectorstore.store_patient_vector(active_patient_id, vector_data, risk_probability)
        except Exception as e:
            st.warning(f"Vector storage note: {str(e)}")

    if current_assessment:
        metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)
        metric_col1.markdown(
            f"""
            <div class="metric-card">
                <div class="metric-label">Heart Disease Risk</div>
                <div class="metric-value">{current_assessment['risk_percentage']}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        metric_col2.markdown(
            f"""
            <div class="metric-card">
                <div class="metric-label">Risk Band</div>
                <div class="metric-value" style="font-size: 1.15rem;">{current_assessment['risk_band']}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        metric_col3.markdown(
            f"""
            <div class="metric-card">
                <div class="metric-label">Care Priority</div>
                <div class="metric-value" style="font-size: 1.05rem;">{current_assessment['care_priority']}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        metric_col4.markdown(
            f"""
            <div class="metric-card">
                <div class="metric-label">Patient ID</div>
                <div class="metric-value" style="font-size: 1.05rem;">{current_assessment['patient_id']}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if current_assessment["risk_probability"] is not None:
            st.progress(min(max(current_assessment["risk_probability"], 0.0), 1.0))

        insight_col, tests_col, suggestion_col = st.columns(3)
        with insight_col:
            st.markdown("### Insights")
            for insight in current_assessment["insights"]:
                st.info(insight)

        with tests_col:
            st.markdown("### Recommended Tests")
            recommended_tests = current_assessment.get("recommended_tests", [])
            if recommended_tests:
                for test_name in recommended_tests:
                    st.info(test_name)
            else:
                st.info("No extra test suggestion was triggered from the current clinical profile.")

        with suggestion_col:
            st.markdown("### Suggestions")
            for suggestion in current_assessment["suggestions"]:
                st.success(suggestion)

        quality_col, benchmark_col = st.columns([1, 1.3])
        with quality_col:
            st.markdown("### Quality & Triage Flags")
            for level, message in current_assessment["quality_flags"]:
                if level == "error":
                    st.error(message)
                elif level == "warning":
                    st.warning(message)
                elif level == "success":
                    st.success(message)
                else:
                    st.info(message)

        with benchmark_col:
            st.markdown("### Population Benchmark")
            if not current_assessment["benchmark_df"].empty:
                st.dataframe(current_assessment["benchmark_df"], use_container_width=True, hide_index=True)
            else:
                st.info("Reference dataset benchmarks are not available in the current workspace.")

        st.markdown(
            f"""
            <div class="panel-card">
                <div class="panel-title">Clinician Handoff Summary</div>
                <div class="panel-text">{current_assessment['handoff_summary']}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown("### Submitted Clinical Snapshot")
        st.dataframe(current_assessment["display_snapshot"], use_container_width=True, hide_index=True)
        render_nearby_doctors_section(
            st.session_state.get("care_location_query", ""),
            current_assessment["risk_band"],
        )

        safe_name = "".join(
            char if char.isalnum() else "_" for char in current_assessment["patient_name"]
        ).strip("_")
        filename_stem = safe_name or "patient"
        export_col1, export_col2 = st.columns(2)
        with export_col1:
            st.download_button(
                label="Download Hospital Report (PDF)",
                data=current_assessment["report_pdf"],
                file_name=f"{filename_stem}_heart_report.pdf",
                mime="application/pdf",
            )
        with export_col2:
            st.download_button(
                label="Download Current Snapshot (CSV)",
                data=current_assessment["display_snapshot"].to_csv(index=False).encode("utf-8"),
                file_name=f"{filename_stem}_snapshot.csv",
                mime="text/csv",
            )
    else:
        st.markdown(
            """
            <div class="panel-card">
                <div class="panel-title">Advanced Workspace Ready</div>
                <div class="panel-text">
                    Submit a patient record to unlock the upgraded dashboard, clinician handoff summary,
                    quality flags, benchmark comparison, PDF report, and the live Execution Project Hub.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

with xray_tab:
    st.markdown(
        """
        <div class="glass-card">
            <div class="section-title">Chest X-Ray Screening</div>
            <div class="panel-text">
                Upload a chest X-ray in a dedicated section to run image-based heart screening, review likely findings,
                and get practical follow-up guidance. This section is separate from the structured clinical-input model.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if xray_bundle.get("enabled"):
        st.success(f"X-ray model ready: {xray_bundle.get('model_name', 'Configured model')}")
    else:
        st.warning(
            "The X-ray workflow is live, but no trained `xray_model.pkl` was found in the project root yet. "
            "Upload still works for preview and quality review, but medical image prediction stays disabled until that model is added. "
            "If you add `xray_model.pkl` while the app is running, the section will detect it and enable prediction automatically."
        )

    if xray_bundle.get("preprocessing"):
        st.markdown(
            "".join([f'<span class="info-chip">{step}</span>' for step in xray_bundle.get("preprocessing", [])]),
            unsafe_allow_html=True,
        )

    default_xray_name = (
        st.session_state.get("latest_assessment", {}) or {}
    ).get("patient_name", "Rahul Sharma")

    with st.form("xray_screening_form"):
        xray_col1, xray_col2 = st.columns([1, 1.2])
        with xray_col1:
            xray_patient_name = st.text_input("Patient name", value=default_xray_name)
            xray_doctor_name = st.text_input("Consulting doctor", value="Dr. A. Mehta")
        with xray_col2:
            uploaded_xray = st.file_uploader(
                "Upload chest X-ray",
                type=["png", "jpg", "jpeg"],
                help="Use a clear chest X-ray image. Posterior-anterior chest views usually work best.",
            )
            st.caption("Supported formats: PNG, JPG, JPEG")

        xray_submitted = st.form_submit_button("Analyze X-Ray")

    if xray_submitted:
        if not uploaded_xray:
            st.error("Please upload a chest X-ray image before running the analysis.")
        else:
            xray_assessment, xray_error = analyze_xray_upload(uploaded_xray, xray_bundle)
            if xray_error:
                st.error(xray_error)
            else:
                xray_assessment["patient_name"] = xray_patient_name.strip() or "Unknown Patient"
                xray_assessment["doctor_name"] = xray_doctor_name.strip() or "Not Provided"
                xray_assessment["file_name"] = uploaded_xray.name
                xray_assessment["analysis_time"] = datetime.now().strftime("%d %b %Y, %I:%M %p")
                st.session_state.latest_xray_assessment = xray_assessment

    current_xray_assessment = st.session_state.get("latest_xray_assessment")
    if current_xray_assessment:
        risk_band = current_xray_assessment.get("risk_band", "Unavailable")
        risk_status_class = get_status_class(risk_band) if risk_band in {"Low", "Medium", "High"} else "status-medium"

        st.markdown(
            f"""
            <div class="glass-card" style="margin-top: 1rem;">
                <div class="status-pill {risk_status_class}">{current_xray_assessment['finding_label']}</div>
                <div class="section-title">X-Ray Review Dashboard</div>
                <div class="panel-text">
                    Patient: {html.escape(current_xray_assessment['patient_name'])} | Doctor: {html.escape(current_xray_assessment['doctor_name'])}
                    | Analyzed: {current_xray_assessment['analysis_time']}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        xray_metric_col1, xray_metric_col2, xray_metric_col3, xray_metric_col4 = st.columns(4)
        xray_metric_col1.metric("Risk Band", risk_band)
        xray_metric_col2.metric("Model Confidence", current_xray_assessment.get("confidence_text", "Not available"))
        xray_metric_col3.metric("Image Size", f"{current_xray_assessment['image_size'][0]} x {current_xray_assessment['image_size'][1]}")
        xray_metric_col4.metric("Model", current_xray_assessment.get("model_name", "Unavailable"))

        preview_col, summary_col = st.columns([1, 1.2])
        with preview_col:
            st.markdown("### Uploaded X-Ray")
            st.image(current_xray_assessment["image_bytes"], use_container_width=True)
            st.caption(current_xray_assessment.get("file_name", "Uploaded image"))

        with summary_col:
            st.markdown("### Likely Problem")
            st.markdown(
                f"""
                <div class="panel-card">
                    <div class="panel-title">{current_xray_assessment['finding_label']}</div>
                    <div class="panel-text">{current_xray_assessment['problem_summary']}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            st.markdown("### What Should I Do?")
            for step in current_xray_assessment.get("next_steps", []):
                if risk_band == "High":
                    st.warning(step)
                elif risk_band == "Medium":
                    st.info(step)
                else:
                    st.success(step)

        quality_col, workflow_col = st.columns(2)
        with quality_col:
            st.markdown("### Image Quality Review")
            for level, message in current_xray_assessment.get("quality_flags", []):
                if level == "warning":
                    st.warning(message)
                elif level == "success":
                    st.success(message)
                else:
                    st.info(message)

        with workflow_col:
            st.markdown("### Workflow Notes")
            if current_xray_assessment.get("prediction_available"):
                st.info("Use this image result together with symptoms, ECG, echo findings, and clinician judgment.")
                st.info("This module is a screening layer and should not be treated as a final diagnosis on its own.")
            else:
                st.warning("Prediction is currently unavailable because a trained X-ray model artifact has not been connected.")
                st.info("Once `xray_model.pkl` is added, this section will use the same workflow to generate a real finding.")

            for step in current_xray_assessment.get("preprocessing", [])[:4]:
                st.caption(f"Pipeline: {step}")

        if risk_band in {"Low", "Medium", "High"}:
            render_nearby_doctors_section(
                st.session_state.get("care_location_query", ""),
                risk_band,
            )
    else:
        st.markdown(
            """
            <div class="panel-card">
                <div class="panel-title">X-Ray Section Ready</div>
                <div class="panel-text">
                    Upload a chest X-ray to preview the image, run the screening pipeline, review likely findings,
                    and see recommended next steps in this separate workspace.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

with symptom_tab:
    st.markdown(
        """
        <div class="glass-card">
            <div class="section-title">Symptom Checker</div>
            <div class="panel-text">
                Use this rule-based pre-screening module to estimate symptom-only heart risk and identify
                which tests may help before a full medical workup. This does not replace the ML model.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.form("symptom_checker_form"):
        st.markdown("### Symptoms Input")
        symptom_col1, symptom_col2 = st.columns(2)

        with symptom_col1:
            chest_pain = st.radio("Chest pain", options=[False, True], format_func=lambda value: "Yes" if value else "No", horizontal=True)
            shortness_of_breath = st.radio("Shortness of breath", options=[False, True], format_func=lambda value: "Yes" if value else "No", horizontal=True)
            fatigue = st.radio("Fatigue", options=[False, True], format_func=lambda value: "Yes" if value else "No", horizontal=True)
            dizziness = st.radio("Dizziness", options=[False, True], format_func=lambda value: "Yes" if value else "No", horizontal=True)

        with symptom_col2:
            irregular_heartbeat = st.radio("Irregular heartbeat", options=[False, True], format_func=lambda value: "Yes" if value else "No", horizontal=True)
            sweating = st.radio("Sweating", options=[False, True], format_func=lambda value: "Yes" if value else "No", horizontal=True)
            nausea = st.radio("Nausea", options=[False, True], format_func=lambda value: "Yes" if value else "No", horizontal=True)
            pain_left_arm_jaw = st.radio("Pain in left arm or jaw", options=[False, True], format_func=lambda value: "Yes" if value else "No", horizontal=True)

        symptom_submitted = st.form_submit_button("Analyze Symptoms")

    if symptom_submitted:
        symptom_inputs = {
            "chest_pain": chest_pain,
            "shortness_of_breath": shortness_of_breath,
            "fatigue": fatigue,
            "dizziness": dizziness,
            "irregular_heartbeat": irregular_heartbeat,
            "sweating": sweating,
            "nausea": nausea,
            "pain_left_arm_jaw": pain_left_arm_jaw,
        }
        symptom_result = get_symptom_risk_result(symptom_inputs)
        symptom_result["recommended_tests"] = get_recommended_tests_from_symptoms(
            symptom_inputs,
            symptom_result["risk_level"],
        )
        symptom_result["guidance"] = get_symptom_guidance(symptom_result["risk_level"])
        st.session_state.latest_symptom_assessment = symptom_result

    symptom_assessment = st.session_state.get("latest_symptom_assessment")
    if symptom_assessment:
        symptom_status_class = get_status_class(symptom_assessment["risk_level"])
        selected_summary = ", ".join(symptom_assessment["selected_labels"]) if symptom_assessment["selected_labels"] else "No symptoms selected"

        st.markdown("### Risk Result")
        st.markdown(
            f"""
            <div class="panel-card">
                <div class="status-pill {symptom_status_class}">{symptom_assessment['risk_level']} Risk</div>
                <div class="panel-title">Symptom-Based Pre-Screening Outcome</div>
                <div class="panel-text">{symptom_assessment['explanation']}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        symptom_metric_col1, symptom_metric_col2, symptom_metric_col3 = st.columns(3)
        symptom_metric_col1.metric("Risk Level", symptom_assessment["risk_level"])
        symptom_metric_col2.metric("Selected Symptoms", symptom_assessment["selected_count"])
        symptom_metric_col3.metric("Concerning Symptoms", symptom_assessment["major_count"])
        st.caption(f"Symptoms flagged: {selected_summary}")

        tests_col, suggestions_col = st.columns(2)
        with tests_col:
            st.markdown("### Recommended Tests")
            if symptom_assessment["recommended_tests"]:
                for test_name in symptom_assessment["recommended_tests"]:
                    st.info(test_name)
            else:
                st.info("No urgent test recommendation was triggered from the current symptom pattern.")

        with suggestions_col:
            st.markdown("### Suggestions")
            for tip in symptom_assessment["guidance"]:
                if symptom_assessment["risk_level"] == "High":
                    st.warning(tip)
                elif symptom_assessment["risk_level"] == "Medium":
                    st.info(tip)
                else:
                    st.success(tip)

        render_nearby_doctors_section(
            st.session_state.get("care_location_query", ""),
            symptom_assessment["risk_level"],
        )

        st.markdown(
            """
            <div class="panel-card">
                <div class="panel-title">How To Use This Module</div>
                <div class="panel-text">
                    This symptom checker is an additional screening layer for early guidance. For a stronger assessment,
                    combine it with the Prediction Studio, vital measurements, and a clinician review.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            """
            <div class="panel-card">
                <div class="panel-title">Pre-Screening Ready</div>
                <div class="panel-text">
                    Submit the symptom form to generate a risk level, explanation, recommended tests,
                    and next-step health suggestions without changing the ML prediction workflow.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

with store_tab:
    st.markdown(
        """
        <div class="glass-card">
            <div class="section-title">🏥 Hindsight Patient Store</div>
            <div class="panel-text">
                Search and analyze patient data with vector-based similarity learning. Discover patterns from historical patient records.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    
    # Initialize vectorstore
    vectorstore = get_vectorstore()
    
    store_section = st.radio("Store Section", ["Search Patient", "Population Insights", "View All Patients", "Learning Analytics"])
    
    if store_section == "Search Patient":
        st.markdown("### 🔍 Search by Patient ID")
        
        col1, col2 = st.columns([3, 1])
        with col1:
            search_id = st.text_input("Enter Patient ID:", placeholder="e.g., PAT-ABC123")
        with col2:
            search_button = st.button("Search", use_container_width=True)
        
        if search_button and search_id:
            vector, data = vectorstore.get_patient_vector(search_id)
            
            if vector is not None:
                # Display patient basic info
                st.success(f"✅ Patient Found: {search_id}")
                
                # Get patient insights
                insights = vectorstore.get_patient_insights(search_id)
                
                # Get visit history
                with st.spinner("Loading patient insights..."):
                    with sqlite3.connect(str(Path('vectorstore.db'))) as conn:
                        history = conn.execute(
                            "SELECT timestamp, diagnosis_result, visit_count FROM patient_vectors WHERE patient_id = ?",
                            (search_id,)
                        ).fetchone()
                
                metric_col1, metric_col2, metric_col3 = st.columns(3)
                with metric_col1:
                    if history:
                        st.metric("Total Visits", history[2])
                with metric_col2:
                    if history and history[1]:
                        st.metric("Latest Risk Score", f"{history[1]*100:.1f}%")
                with metric_col3:
                    if insights:
                        st.metric("Risk Percentile", f"{insights.get('risk_percentile', 'N/A'):.1f}%")
                
                # Tab for detailed info
                patient_info_tab, similar_tab, patterns_tab = st.tabs(["Patient Data", "Similar Patients", "Risk Patterns"])
                
                with patient_info_tab:
                    st.markdown("#### Clinical Data")
                    data_cols = st.columns(4)
                    if data:
                        metrics_list = [
                            ("Age", f"{int(data.get('age', 'N/A'))} years"),
                            ("Gender", f"{['Female', 'Male'][int(data.get('sex', 0))] if isinstance(data.get('sex'), (int, float)) else data.get('sex')}"),
                            ("Chest Pain Type", str(data.get('cp', 'N/A'))),
                            ("Blood Pressure", f"{int(data.get('trestbps', 'N/A'))} mmHg"),
                            ("Cholesterol", f"{int(data.get('chol', 'N/A'))} mg/dL"),
                            ("Max Heart Rate", f"{int(data.get('thalach', 'N/A'))} bpm"),
                            ("Oldpeak", f"{float(data.get('oldpeak', 0)):.1f}"),
                            ("Major Vessels", str(data.get('ca', 'N/A'))),
                        ]
                        
                        for idx, (label, value) in enumerate(metrics_list):
                            st.metric(label, value)
                
                with similar_tab:
                    st.markdown("#### Similar Patients (Vector Similarity)")
                    similar_patients = vectorstore.similarity_search(search_id, top_k=5)
                    
                    if similar_patients:
                        for i, (pid, similarity, pdata) in enumerate(similar_patients, 1):
                            with st.expander(f"🔗 Similar Patient {i} - {pid} (Similarity: {similarity*100:.1f}%)", expanded=(i==1)):
                                col1, col2 = st.columns(2)
                                with col1:
                                    st.metric("Patient ID", pid)
                                    st.metric("Age", f"{int(pdata.get('age', 'N/A'))} years")
                                with col2:
                                    st.metric("Similarity Score", f"{similarity*100:.1f}%")
                                    st.metric("Blood Pressure", f"{int(pdata.get('trestbps', 'N/A'))} mmHg")
                    else:
                        st.info("No similar patients found in the system yet.")
                
                with patterns_tab:
                    st.markdown("#### Risk Pattern Analysis")
                    if insights:
                        col1, col2 = st.columns(2)
                        with col1:
                            st.metric("Risk Percentile", f"{insights.get('risk_percentile', 'N/A'):.1f}%")
                            st.info("Your risk score compared to other patients in the system")
                        with col2:
                            if insights.get('clusters'):
                                st.metric("Cluster Count", len(insights['clusters']))
                                st.success("Patient belongs to identified clusters")
                        
                        # Population comparison
                        pop_mean = insights.get('population_mean', [])
                        if pop_mean and isinstance(pop_mean, list) and len(pop_mean) > 0:
                            st.markdown("**Population vs Patient Comparison**")
                            comparison_data = {
                                'Your Profile': vector[:5].tolist() if len(vector) >= 5 else vector.tolist(),
                                'Population Mean': pop_mean[:5] if len(pop_mean) >= 5 else pop_mean,
                            }
                            st.bar_chart(comparison_data)
            else:
                st.error(f"❌ No patient found with ID: {search_id}")
                st.info("Patient data will be available after their first checkup in the system.")
    
    elif store_section == "Population Insights":
        st.markdown("### 📊 Population Learning Insights")
        
        patterns = vectorstore.learn_patterns()
        
        if patterns.get('status') == 'insufficient_data':
            st.warning(f"⏳ Need at least 5 patient records for pattern learning. Current: {patterns.get('count', 0)}/5")
        else:
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Total Patients", patterns.get('total_patients', 0))
            with col2:
                st.metric("Patient Clusters", len(patterns.get('clusters', [])))
            with col3:
                st.metric("Mean Age", f"{patterns.get('mean_patient_profile', [0])[0]:.1f}")
            with col4:
                st.metric("Risk Variation", f"{patterns.get('risk_variation', [0])[0]:.2f}")
            
            st.markdown("#### Cluster Profiles")
            clusters = patterns.get('clusters', [])
            if clusters:
                for idx, cluster in enumerate(clusters, 1):
                    with st.expander(f"Cluster {idx} - {len(cluster['patient_ids'])} patients", expanded=(idx==1)):
                        st.metric("Cluster Size", len(cluster['patient_ids']))
                        st.metric("Type", cluster.get('commonality', 'N/A'))
                        st.write("**Patients in cluster:**")
                        for pid in cluster['patient_ids']:
                            st.write(f"• {pid}")
            else:
                st.info("Not enough patient diversity for cluster analysis yet.")
    
    elif store_section == "View All Patients":
        st.markdown("### 📋 All Stored Patients")
        
        all_patients = vectorstore.get_all_patients_summary()
        
        if all_patients:
            # Create display dataframe
            display_df = pd.DataFrame([
                {
                    'Patient ID': p['patient_id'],
                    'Age': p['age'],
                    'Gender': p['sex'],
                    'Visit Count': p['visit_count'],
                    'Latest Risk Score': f"{p['diagnosis_result']*100:.1f}%" if p['diagnosis_result'] else "N/A",
                    'Last Visit': p['timestamp']
                }
                for p in all_patients
            ])
            
            st.dataframe(display_df, use_container_width=True)
            
            st.markdown("#### Statistics")
            stats_col1, stats_col2, stats_col3 = st.columns(3)
            with stats_col1:
                st.metric("Total Patients", len(all_patients))
            with stats_col2:
                avg_visits = np.mean([p['visit_count'] for p in all_patients]) if all_patients else 0
                st.metric("Avg Visits per Patient", f"{avg_visits:.1f}")
            with stats_col3:
                avg_risk = np.mean([p['diagnosis_result'] for p in all_patients if p['diagnosis_result']]) if all_patients else 0
                st.metric("Avg Risk Score", f"{avg_risk*100:.1f}%")
        else:
            st.info("No patient data stored yet. Complete checkups to populate the store.")
    
    elif store_section == "Learning Analytics":
        st.markdown("### 🧠 Vector Learning Analytics")
        
        patterns = vectorstore.learn_patterns()
        
        if patterns.get('status') != 'insufficient_data':
            st.success(f"✅ Learned from {patterns.get('total_patients', 0)} patients")
            
            analytics_tab1, analytics_tab2, analytics_tab3 = st.tabs(
                ["Risk Distribution", "Pattern Profiles", "Recommendations"]
            )
            
            with analytics_tab1:
                st.markdown("#### Risk Level Distribution")
                all_patients = vectorstore.get_all_patients_summary()
                if all_patients:
                    risk_scores = [p['diagnosis_result'] for p in all_patients if p['diagnosis_result']]
                    if risk_scores:
                        fig_data = {
                            'Low Risk (<35%)': len([r for r in risk_scores if r < 0.35]),
                            'Medium Risk (35-65%)': len([r for r in risk_scores if 0.35 <= r < 0.65]),
                            'High Risk (>65%)': len([r for r in risk_scores if r >= 0.65]),
                        }
                        st.bar_chart(fig_data)
            
            with analytics_tab2:
                st.markdown("#### Vector Pattern Profiles")
                mean_profile = patterns.get('mean_patient_profile', [])
                high_risk_profile = patterns.get('high_risk_pattern', [])
                low_risk_profile = patterns.get('low_risk_pattern', [])
                
                feature_labels = ['Age-norm', 'Sex-norm', 'CP-norm', 'BP-norm', 'Chol-norm']
                
                if mean_profile and len(mean_profile) > 0:
                    profile_data = {
                        'Population Mean': mean_profile[:5],
                        'High-Risk Pattern': high_risk_profile[:5] if high_risk_profile else mean_profile[:5],
                        'Low-Risk Pattern': low_risk_profile[:5] if low_risk_profile else mean_profile[:5],
                    }
                    st.line_chart(profile_data)
            
            with analytics_tab3:
                st.markdown("#### System Recommendations")
                all_patients = vectorstore.get_all_patients_summary()
                high_risk_count = len([p for p in all_patients if p['diagnosis_result'] and p['diagnosis_result'] > 0.65])
                
                col1, col2 = st.columns(2)
                with col1:
                    if high_risk_count > 2:
                        st.warning(f"⚠️ High-Risk Alert: {high_risk_count} patients with risk >65% detected")
                    else:
                        st.info(f"ℹ️ Current high-risk patients: {high_risk_count}")
                
                with col2:
                    if len(all_patients) > 10:
                        st.success(f"✅ Good coverage: {len(all_patients)} patients in learning database")
                    else:
                        st.info(f"📈 Continue collecting data: {len(all_patients)}/10 recommended for robust patterns")
        else:
            st.info("📚 Waiting for more patient data... Need at least 5 checkups to activate pattern learning.")


with hub_tab:
    st.markdown("### Execution Project Hub")
    st.write(
        "Track every screening run in one place with session analytics, trend visibility, and export-ready history."
    )
    history = st.session_state.get("assessment_history", [])
    latest_assessment = st.session_state.get("latest_assessment")

    if history:
        history_df = pd.DataFrame(history)
        total_runs = len(history_df)
        high_risk_runs = int((history_df["Risk Band"] == "High").sum())
        average_risk = float(history_df["Risk Score (%)"].mean())
        latest_priority = history_df.iloc[0]["Care Priority"]

        exec_col1, exec_col2, exec_col3, exec_col4 = st.columns(4)
        exec_col1.metric("Total Assessments", total_runs)
        exec_col2.metric("High-Risk Flags", high_risk_runs)
        exec_col3.metric("Average Risk", f"{average_risk:.1f}%")
        exec_col4.metric("Latest Priority", latest_priority)

        chart_col1, chart_col2 = st.columns(2)
        with chart_col1:
            st.markdown("#### Risk Trend")
            trend_df = history_df.iloc[::-1].reset_index(drop=True)
            trend_df.index = range(1, len(trend_df) + 1)
            st.line_chart(trend_df[["Risk Score (%)"]], use_container_width=True)

        with chart_col2:
            st.markdown("#### Risk Band Mix")
            band_order = ["Low", "Medium", "High"]
            band_counts = (
                history_df["Risk Band"]
                .value_counts()
                .reindex(band_order, fill_value=0)
                .reset_index()
            )
            band_counts.columns = ["Risk Band", "Count"]
            st.bar_chart(band_counts.set_index("Risk Band"), use_container_width=True)

        if latest_assessment:
            st.markdown(
                f"""
                <div class="panel-card">
                    <div class="panel-title">Latest Handoff Brief</div>
                    <div class="panel-text">{latest_assessment['handoff_summary']}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        st.markdown("#### Session Assessment Ledger")
        st.dataframe(history_df, use_container_width=True, hide_index=True)
        st.download_button(
            label="Export Execution Hub CSV",
            data=history_df.to_csv(index=False).encode("utf-8"),
            file_name="execution_project_hub_history.csv",
            mime="text/csv",
        )
    else:
        st.info("No assessments have been submitted yet. Run a patient screening in Prediction Studio to populate the hub.")

with chat_tab:
    initialize_chat_state()
    st.markdown(
        """
        <div class="glass-card">
            <div class="section-title">🤖 Hindsight Smart Health Chat</div>
            <div class="panel-text">
                Chat with a health assistant that remembers your profile, stores symptoms, and learns from past patient data.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    user_id = st.text_input("Chat User ID", value=st.session_state.chat_user_id)
    chat_input = st.text_area("Message", height=120, placeholder="Ask about your symptoms, risk, or similar patient cases...")
    send_button = st.button("Send Message", use_container_width=True)

    if send_button and chat_input.strip():
        st.session_state.chat_user_id = user_id
        response = _build_chat_response(chat_input, user_id)
        st.session_state.chat_history.append({"speaker": "You", "message": chat_input})
        st.session_state.chat_history.append({"speaker": "HealthBot", "message": response["response"]})

    if st.session_state.chat_history:
        st.markdown("### Conversation")
        _render_chat_history()

    with st.expander("Memory Snapshot", expanded=True):
        _render_memory_snapshot(user_id)

    with st.expander("Learning Summary", expanded=False):
        vectorstore = get_vectorstore()
        patterns = vectorstore.learn_patterns()
        if patterns.get("status") == "insufficient_data":
            st.info(f"Need at least 5 patient records for vector-based learning. Currently {patterns.get('count', 0)}.")
        else:
            st.metric("Total Patients Learned", patterns.get("total_patients", 0))
            st.metric("Cluster Count", len(patterns.get("clusters", [])))
            st.write("**Population learning summary:**")
            st.write(
                f"Learned mean patient profile and identified {len(patterns.get('clusters', []))} clusters from historical patient data."
            )
            if patterns.get("clusters"):
                for idx, cluster in enumerate(patterns.get("clusters", []), 1):
                    st.write(f"- Cluster {idx}: {len(cluster['patient_ids'])} patients")

with model_tab:
    st.markdown("### Why This Model Is More Reliable")
    preprocessing = bundle.get("preprocessing", [])
    if preprocessing:
        st.markdown("".join([f'<span class="info-chip">{step}</span>' for step in preprocessing]), unsafe_allow_html=True)

    overview_col1, overview_col2 = st.columns(2)
    with overview_col1:
        st.markdown("#### Model Metrics")
        if metrics:
            st.write(f"Accuracy: `{metrics.get('accuracy', 0) * 100:.2f}%`")
            st.write(f"Macro F1: `{metrics.get('macro_f1', 0) * 100:.2f}%`")
        else:
            st.write("Metrics metadata is not available in the current model artifact.")

        class_distribution = dataset_summary.get("class_distribution", {})
        if class_distribution:
            st.markdown("#### Dataset Balance")
            st.write(class_distribution)
            imbalance_strategy = dataset_summary.get("imbalance_strategy")
            if imbalance_strategy:
                st.caption(imbalance_strategy)

    with overview_col2:
        st.markdown("#### Confusion Matrix")
        confusion_matrix_data = metrics.get("confusion_matrix")
        if confusion_matrix_data:
            confusion_df = pd.DataFrame(
                confusion_matrix_data,
                index=["Actual High Risk", "Actual Low Risk"],
                columns=["Predicted High Risk", "Predicted Low Risk"],
            )
            st.dataframe(confusion_df, use_container_width=True)
        else:
            st.write("Confusion matrix metadata is not available.")

    st.markdown("#### Top Model Drivers")
    if feature_importance:
        feature_importance_df = (
            pd.DataFrame(
                [{"Feature": FEATURE_LABELS.get(feature, feature), "Importance": score} for feature, score in feature_importance.items()]
            )
            .sort_values("Importance", ascending=False)
            .reset_index(drop=True)
        )
        st.bar_chart(feature_importance_df.set_index("Feature"))
    else:
        st.write("Feature importance metadata is not available.")

with insights_tab:
    st.markdown("### Integrated iNSIGHTS Experience")
    st.write(
        "The live iNSIGHTS site is attached here so your project combines predictive healthcare and a broader AI assistant experience."
    )
    components.iframe(INSIGHTS_EMBED_URL, height=920, scrolling=True)

with project_suite_tab:
    st.markdown(
        """
        <div class="glass-card">
            <div class="section-title">AI Project Suite</div>
            <div class="panel-text">
                These advanced builder tools extend your iNSIGHTS and Execution Project Hub story with structured delivery,
                continuation planning, and product-research guidance for the next phase of the project.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    todo_engine_tab, grant_tab, deep_search_tab = st.tabs(
        [
            "Structured AI To-Do Engine",
            "Continuation Grant + Onboarding",
            "Product Thinking Deep Search",
        ]
    )

    latest_assessment = st.session_state.get("latest_assessment")
    latest_symptom_assessment = st.session_state.get("latest_symptom_assessment")
    session_history = st.session_state.get("assessment_history", [])
    location_query = st.session_state.get("care_location_query", "")

    with todo_engine_tab:
        st.markdown("### Structured AI To-Do Engine")
        st.write(
            "Generate a prioritized execution list from the current state of your screening app, care workflows, and project operations."
        )
        todo_items = build_structured_todo_items(
            latest_assessment=latest_assessment,
            latest_symptom_assessment=latest_symptom_assessment,
            session_history=session_history,
            location_query=location_query,
        )
        todo_df = pd.DataFrame(todo_items)

        todo_col1, todo_col2, todo_col3 = st.columns(3)
        todo_col1.metric("Open Items", len(todo_items))
        todo_col2.metric("Live Runs", len(session_history))
        todo_col3.metric(
            "Risk Context",
            latest_assessment.get("risk_band", "No ML run") if latest_assessment else "No ML run",
        )

        st.dataframe(todo_df, use_container_width=True, hide_index=True)
        st.download_button(
            label="Export Structured To-Do CSV",
            data=todo_df.to_csv(index=False).encode("utf-8"),
            file_name="structured_ai_todo_engine.csv",
            mime="text/csv",
        )

    with grant_tab:
        st.markdown("### Continuation Grant + Onboarding")
        st.write(
            "Turn the current demo into a pilot-ready story with a funding narrative, onboarding plan, and milestone checklist."
        )

        with st.form("grant_onboarding_form"):
            grant_col1, grant_col2 = st.columns(2)
            with grant_col1:
                pilot_partner = st.text_input("Pilot partner", value="Community hospital or hackathon demo partner")
                target_group = st.text_input("Target group", value="screening-stage cardiac patients and preventive care users")
            with grant_col2:
                deployment_region = st.text_input("Deployment region", value=location_query.strip() or "New Delhi")
                funding_goal = st.text_input("Funding goal", value="a small continuation grant")
            grant_submitted = st.form_submit_button("Build Continuation Package")

        if grant_submitted or True:
            grant_bundle = build_continuation_grant_bundle(
                pilot_partner=pilot_partner,
                deployment_region=deployment_region,
                target_group=target_group,
                funding_goal=funding_goal,
                latest_assessment=latest_assessment,
                latest_symptom_assessment=latest_symptom_assessment,
                session_history=session_history,
            )

            st.markdown("#### Mission")
            st.info(grant_bundle["mission"])

            st.markdown("#### Continuation Story")
            st.markdown(
                f"""
                <div class="panel-card">
                    <div class="panel-text">{grant_bundle['continuation_story']}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            grant_left, grant_right = st.columns(2)
            with grant_left:
                st.markdown("#### Funding Use")
                for item in grant_bundle["funding_use"]:
                    st.success(item)

                st.markdown("#### Onboarding Plan")
                for step in grant_bundle["onboarding_steps"]:
                    st.info(step)

            with grant_right:
                st.markdown("#### Success Metrics")
                for metric in grant_bundle["success_metrics"]:
                    st.warning(metric)

                continuation_text = "\n".join(
                    [
                        "Mission:",
                        grant_bundle["mission"],
                        "",
                        "Continuation Story:",
                        grant_bundle["continuation_story"],
                        "",
                        "Funding Use:",
                        *[f"- {item}" for item in grant_bundle["funding_use"]],
                        "",
                        "Onboarding Plan:",
                        *[f"- {item}" for item in grant_bundle["onboarding_steps"]],
                        "",
                        "Success Metrics:",
                        *[f"- {item}" for item in grant_bundle["success_metrics"]],
                    ]
                )
                st.download_button(
                    label="Download Grant + Onboarding Brief",
                    data=continuation_text.encode("utf-8"),
                    file_name="continuation_grant_onboarding_brief.txt",
                    mime="text/plain",
                )

    with deep_search_tab:
        st.markdown("### Product Thinking Deep Search")
        st.write(
            "Build sharper product strategy by generating deep-search angles, source targets, and experiments around your next growth question."
        )

        deep_col1, deep_col2, deep_col3 = st.columns(3)
        with deep_col1:
            search_goal = st.selectbox(
                "Search goal",
                options=[
                    "Clinical Adoption",
                    "User Retention",
                    "Diagnostic Partnerships",
                    "Healthcare AI Safety",
                ],
            )
        with deep_col2:
            user_segment = st.text_input("User segment", value="patients and clinicians")
        with deep_col3:
            deep_region = st.text_input("Research region", value=location_query.strip() or "India")

        deep_search_bundle = build_product_deep_search_bundle(
            search_goal=search_goal,
            user_segment=user_segment,
            deployment_region=deep_region,
        )

        st.markdown("#### Problem Statement")
        st.markdown(
            f"""
            <div class="panel-card">
                <div class="panel-text">{deep_search_bundle['problem_statement']}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        deep_left, deep_right = st.columns(2)
        with deep_left:
            st.markdown("#### Deep Search Questions")
            for question in deep_search_bundle["deep_questions"]:
                st.info(question)

            st.markdown("#### Recommended Sources")
            for source in deep_search_bundle["recommended_sources"]:
                st.success(source)

        with deep_right:
            st.markdown("#### Search Queries")
            st.code("\n".join(deep_search_bundle["search_queries"]), language="text")

            st.markdown("#### Experiment Tracks")
            for experiment in deep_search_bundle["experiment_tracks"]:
                st.warning(experiment)
