"""Flask AI Health Assistant

This Flask application integrates:
- Heart disease prediction using an existing model file
- Chatbot interaction with persistent memory via Hindsight API
- Memory storage for name, age, symptoms, previous risk results

Endpoints:
- POST /chat
- POST /predict

Use JSON requests and responses.

Example usage:

curl -X POST http://127.0.0.1:5000/chat -H "Content-Type: application/json" -d '{"user_id": "user123", "message": "My name is Manik"}'

curl -X POST http://127.0.0.1:5000/predict -H "Content-Type: application/json" -d '{"user_id":"user123","features":{"age":52,"sex":1,"cp":2,"trestbps":140,"chol":215,"fbs":0,"restecg":1,"thalach":160,"exang":0,"oldpeak":1.8,"slope":2,"ca":0,"thal":2}}'
"""

import os
import pickle
import re
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from flask import Flask, jsonify, request

try:
    from openai import OpenAI, APIError, APIConnectionError
except ImportError:
    OpenAI = None

from assistant_memory import get_memory, save_memory, update_memory, MemoryResult

load_dotenv()

# OpenAI Configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_CLIENT = OpenAI(api_key=OPENAI_API_KEY) if OpenAI and OPENAI_API_KEY else None
OPENAI_MODEL = "gpt-4o-mini"

MODEL_PATH = os.getenv("HEART_MODEL_PATH", "model.pkl")
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
SYMPTOM_KEYWORDS = [
    "chest pain",
    "shortness of breath",
    "fatigue",
    "dizziness",
    "nausea",
    "palpitations",
    "sweating",
    "palpitation",
    "breath",
    "pressure",
    "tightness",
    "pain",
]

app = Flask(__name__)
model = None


def load_model() -> Any:
    """Load the heart disease model from disk."""
    global model
    if model is not None:
        return model
    if not os.path.isfile(MODEL_PATH):
        raise FileNotFoundError(f"Heart disease model not found at {MODEL_PATH}")
    with open(MODEL_PATH, "rb") as f:
        model = pickle.load(f)
    return model


def _build_feature_vector(features: Dict[str, Any]) -> List[float]:
    """Convert request feature map into ordered model input."""
    vector = []
    for field in FEATURE_COLUMNS:
        if field not in features:
            raise ValueError(f"Missing feature: {field}")
        vector.append(float(features[field]))
    return vector


def _safe_extract_name(message: str) -> Optional[str]:
    """Find a name phrase in the user message."""
    patterns = [
        r"my name is (?P<name>[A-Za-z ]+)",
        r"i am (?P<name>[A-Za-z ]+)",
        r"i'm (?P<name>[A-Za-z ]+)",
    ]
    text = message.lower()
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            name = match.group("name").strip()
            if len(name) > 1:
                return name.title()
    return None


def _safe_extract_age(message: str) -> Optional[int]:
    """Extract age from user message in various formats."""
    patterns = [
        r"i am (\d+) years? old",
        r"i'm (\d+) years? old",
        r"age[:\s]+(\d+)",
        r"my age is (\d+)",
        r"age (\d+)",
        r"(\d+) year[s]? old",
    ]
    text = message.lower()
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            age_str = match.group(1).strip()
            try:
                age = int(age_str)
                if 1 <= age <= 150:  # Sanity check
                    return age
            except ValueError:
                continue
    return None


def _find_symptoms(message: str) -> List[str]:
    """Extract symptom keywords from the user message."""
    text = message.lower()
    symptoms = []
    for keyword in SYMPTOM_KEYWORDS:
        if keyword in text and keyword not in symptoms:
            symptoms.append(keyword)
    return symptoms


def _read_memory(user_id: str, key: str) -> Optional[Any]:
    """Read a memory value if it exists."""
    result = get_memory(user_id, key)
    return result.value if result else None


def _store_user_attribute(user_id: str, key: str, value: Any) -> Dict[str, Any]:
    """Save or update a user memory attribute."""
    existing = _read_memory(user_id, key)
    if existing is None:
        saved = save_memory(user_id, key, value)
    else:
        saved = update_memory(user_id, key, value)
    return {"user_id": user_id, "key": key, "value": value, "source": saved.source}


def _merge_symptom_lists(existing: List[str], new_symptoms: List[str]) -> List[str]:
    merged = list(dict.fromkeys(existing + new_symptoms))
    return merged


def _build_personalized_greeting(user_id: str) -> str:
    name = _read_memory(user_id, "name")
    if name:
        return f"Welcome back, {name}! I'm here to help with your heart health."
    return "Hello there! I'm your AI Health Assistant. How can I support you today?"


def _format_symptoms(symptoms: List[str]) -> str:
    if not symptoms:
        return "I don't have any symptoms saved for you yet."
    return "I have recorded the following symptoms: " + ", ".join(symptoms) + "."


def _compare_risk(user_id: str, current_risk: float) -> Dict[str, Any]:
    previous_risk = _read_memory(user_id, "previous_risk")
    if previous_risk is None:
        return {"status": "first_record", "message": "This is your first recorded heart risk."}

    if current_risk > float(previous_risk):
        return {
            "status": "risk_increased",
            "message": f"Your current risk ({current_risk:.1%}) is higher than your previous risk ({float(previous_risk):.1%}). Please review your health plan and speak with a clinician.",
        }
    return {
        "status": "risk_stable_or_lower",
        "message": f"Your risk is {current_risk:.1%}, which is stable or improved from the previous value of {float(previous_risk):.1%}. Keep following your care plan.",
    }


def generate_ai_response(
    user_input: str,
    prediction: Optional[int] = None,
    memory_context: Optional[Dict[str, Any]] = None,
    conversation_history: Optional[List[Dict[str, str]]] = None,
) -> str:
    """
    Generate AI-powered healthcare assistant response using OpenAI API.
    
    Args:
        user_input: User's message
        prediction: Heart disease prediction (0=LOW RISK, 1=HIGH RISK)
        memory_context: Dict with keys: name, age, symptoms, previous_risk
        conversation_history: List of prior messages for multi-turn context
    
    Returns:
        str: AI-generated response text
    """
    if not OPENAI_CLIENT or not OPENAI_API_KEY:
        return "I'm currently unavailable. Please try again later or consult a healthcare professional."

    context_parts = []
    if memory_context:
        name = memory_context.get("name")
        age = memory_context.get("age")
        symptoms = memory_context.get("symptoms")
        previous_risk = memory_context.get("previous_risk")

        if name:
            context_parts.append(f"User name: {name}")
        if age is not None:
            context_parts.append(f"Age: {age}")
        if symptoms:
            context_parts.append(f"Reported symptoms: {', '.join(symptoms)}")
        if previous_risk is not None:
            context_parts.append(f"Previous risk score: {previous_risk:.1%}")

    if prediction == 1:
        context_parts.append("Urgent: High risk heart disease screening result.")
    elif prediction == 0:
        context_parts.append("Low risk heart disease screening result.")

    system_prompt = """You are a compassionate, practical, and knowledgeable healthcare AI assistant specializing in heart health.

Your responsibilities:
1. Listen carefully to patient concerns and symptoms.
2. Provide evidence-based health information.
3. Recognize warning signs of serious conditions.
4. Always give concrete next steps and suggestions.
5. Encourage professional medical consultation when appropriate.

Guidelines:
- For serious symptoms (chest pain, severe shortness of breath, dizziness with syncope): STRONGLY recommend immediate doctor/ER evaluation.
- For moderate symptoms: suggest specific tests like ECG, Blood Pressure monitoring, or a cholesterol panel.
- For low-risk cases: suggest prevention, monitoring, and follow-up care.
- If the user lacks detail, ask one clear follow-up question.
- Include at least one actionable recommendation or practical next step.
- Keep responses concise, warm, and easy to understand.
- Use simple, clear language (avoid jargon).
- Never provide a definitive diagnosis or medication advice.
- Do not replace professional medical consultation.
"""

    user_message = "".join([part + ". " for part in context_parts]) + f"Patient says: {user_input}"
    messages = [{"role": "system", "content": system_prompt}]
    if conversation_history:
        for item in conversation_history:
            if item.get("role") in {"user", "assistant"} and item.get("content"):
                messages.append({"role": item["role"], "content": item["content"]})
    messages.append({"role": "user", "content": user_message})

    try:
        try:
            response = OPENAI_CLIENT.chat.completions.create(
                model=OPENAI_MODEL,
                messages=messages,
                temperature=0.7,
                max_tokens=220,
                timeout=12,
            )
            return response.choices[0].message.content.strip()
        except Exception as first_error:
            print(f"Chat completions error, trying responses API: {first_error}")
            response = OPENAI_CLIENT.responses.create(
                model=OPENAI_MODEL,
                messages=messages,
                temperature=0.7,
                max_tokens=220,
                timeout=12,
            )
            if hasattr(response, "output_text") and response.output_text:
                return response.output_text.strip()
            if hasattr(response, "output") and response.output:
                output = response.output
                if isinstance(output, list) and output:
                    first = output[0]
                    if isinstance(first, dict) and first.get("content"):
                        content = first["content"]
                        if isinstance(content, list) and content:
                            return content[0].get("text", "").strip()
            raise
    except (APIError, APIConnectionError) as e:
        print(f"OpenAI API error: {e}")
        if prediction == 1:
            return "Your heart health needs immediate attention. Please consult a doctor or visit the ER right away."
        elif prediction == 0:
            return "Based on screening, your heart risk is low. Continue healthy habits and schedule regular check-ups."
        else:
            return "Please describe your symptoms in detail so I can better assist you. Consider scheduling a doctor's appointment for professional evaluation."
    except Exception as e:
        print(f"Unexpected error in AI response generation: {e}")
        return "I apologize, but I'm having technical difficulties. Please consult with a healthcare professional."


def chatbot_response(message: str, user_id: str) -> Dict[str, Any]:
    """Generate a chatbot response using persistent Hindsight memory."""
    normalized = message.strip()
    details = {"memory_actions": []}

    # Extract all information first
    extracted_name = _safe_extract_name(normalized)
    extracted_age = _safe_extract_age(normalized)
    extracted_symptoms = _find_symptoms(normalized)
    
    # Store any extracted information
    if extracted_name:
        _store_user_attribute(user_id, "name", extracted_name)
        details["memory_actions"].append({"key": "name", "value": extracted_name})
    
    if extracted_age is not None:
        _store_user_attribute(user_id, "age", extracted_age)
        details["memory_actions"].append({"key": "age", "value": extracted_age})
    
    if extracted_symptoms:
        existing_symptoms = _read_memory(user_id, "symptoms") or []
        merged = _merge_symptom_lists(existing_symptoms, extracted_symptoms)
        _store_user_attribute(user_id, "symptoms", merged)
        details["memory_actions"].append({"key": "symptoms", "value": merged})
    
    # Decide what to respond based on what was extracted or queried
    if extracted_name and not extracted_age and not extracted_symptoms:
        return {
            "response": f"Nice to meet you, {extracted_name}. I will remember your name for future chat sessions.",
            "details": details,
        }
    
    if extracted_age is not None and not extracted_name and not extracted_symptoms:
        return {
            "response": f"Got it! I've noted that you are {extracted_age} years old. This will help me provide better health guidance.",
            "details": details,
        }
    
    if extracted_symptoms and not extracted_name and not extracted_age:
        merged_symptoms = _read_memory(user_id, "symptoms") or []
        suggestion_text = ""
        serious = any(symptom in ["chest pain", "shortness of breath", "irregular heartbeat", "pain in left arm", "pain in jaw"] for symptom in merged_symptoms)
        if serious:
            suggestion_text = "This sounds concerning, so please seek prompt medical evaluation and consider getting an ECG, blood pressure check, and a cardiology review."
        else:
            suggestion_text = "Monitor your symptoms closely, schedule a checkup, and consider a blood pressure or cholesterol screen."
        return {
            "response": f"I've noted your symptoms: {', '.join(merged_symptoms)}. {suggestion_text}",
            "details": details,
        }
    
    # If multiple fields extracted, acknowledge all
    if extracted_name or extracted_age or extracted_symptoms:
        responses = []
        if extracted_name:
            responses.append(f"Nice to meet you, {extracted_name}")
        if extracted_age is not None:
            responses.append(f"noted your age is {extracted_age}")
        if extracted_symptoms:
            responses.append(f"recorded symptoms: {', '.join(extracted_symptoms)}")
        combined_response = ". I've ".join(responses) + ". I will track this information and suggest a medical review if needed."
        if combined_response.startswith("."):
            combined_response = combined_response[2:]
        return {
            "response": combined_response,
            "details": details,
        }

    if re.search(r"what is my name|who am i|do you know my name", normalized, re.IGNORECASE):
        stored_name = _read_memory(user_id, "name")
        if stored_name:
            return {"response": f"Your name is {stored_name}.", "details": details}
        return {"response": "I don't have your name yet. Please tell me your name so I can remember it.", "details": details}

    if re.search(r"what is my age|how old am i|do you know my age", normalized, re.IGNORECASE):
        stored_age = _read_memory(user_id, "age")
        if stored_age is not None:
            return {"response": f"You are {stored_age} years old.", "details": details}
        return {"response": "I don't have your age yet. Please tell me how old you are.", "details": details}

    if re.search(r"previous risk|last result|heart risk|risk result", normalized, re.IGNORECASE):
        previous_risk = _read_memory(user_id, "previous_risk")
        if previous_risk is not None:
            return {
                "response": f"Your stored risk score is {float(previous_risk):.1%}. If you provide updated health measurements, I can compare it with a new prediction.",
                "details": details,
            }
        return {"response": "I don't have a previous risk score saved yet. You can run a prediction through /predict.", "details": details}

    if re.search(r"how am i|how am i feeling|check my health|health suggestion", normalized, re.IGNORECASE):
        symptoms_list = _read_memory(user_id, "symptoms") or []
        name = _read_memory(user_id, "name")
        greetings = f"Hey {name}, " if name else "" 
        if symptoms_list:
            return {
                "response": greetings + "I recommend that you keep monitoring symptoms like " + ", ".join(symptoms_list) + ". If your heart risk has increased, consider consulting your doctor.",
                "details": details,
            }
        return {
            "response": greetings + "I don't have enough symptom details yet. Please tell me how you are feeling or use /predict to evaluate your risk.",
            "details": details,
        }

    if re.search(r"memory|remember|forgot|what do you know", normalized, re.IGNORECASE):
        profile = {
            "name": _read_memory(user_id, "name"),
            "age": _read_memory(user_id, "age"),
            "symptoms": _read_memory(user_id, "symptoms"),
            "previous_risk": _read_memory(user_id, "previous_risk"),
        }
        profile_lines = [f"{key.capitalize()}: {value}" for key, value in profile.items() if value is not None]
        if profile_lines:
            return {"response": "I remember: " + "; ".join(profile_lines), "details": details}
        return {"response": "I don't have any memory for you yet. Share your name, age, symptoms, or risk information.", "details": details}

    if re.search(r"hello|hi|hey|good morning|good evening", normalized, re.IGNORECASE):
        name = _read_memory(user_id, "name")
        if name:
            return {"response": f"Hello again, {name}! How can I help with your heart wellness today?", "details": details}
        return {"response": "Hello! I'm your AI Health Assistant. What would you like to do today?", "details": details}

    return {
        "response": _build_personalized_greeting(user_id) + " Tell me what you'd like to discuss about your heart health.",
        "details": details,
    }


@app.route("/predict", methods=["POST"])
def predict():
    """Predict heart disease risk and save it as persistent memory."""
    try:
        payload = request.get_json(force=True)
        user_id = payload.get("user_id")
        features = payload.get("features")
        if not user_id or not isinstance(features, dict):
            return jsonify({"error": "Please provide user_id and features in JSON."}), 400

        model = load_model()
        vector = _build_feature_vector(features)
        probability = None

        if hasattr(model, "predict_proba"):
            probability = float(model.predict_proba([vector])[0][1])
        else:
            probability = float(model.predict([vector])[0])

        compare_result = _compare_risk(user_id, probability)
        save_memory(user_id, "previous_risk", probability)
        save_memory(user_id, "age", features.get("age"))
        if "name" not in features and _read_memory(user_id, "name") is None:
            name_guess = payload.get("name")
            if name_guess:
                save_memory(user_id, "name", name_guess)

        response = {
            "user_id": user_id,
            "risk_score": probability,
            "risk_percent": f"{probability:.1%}",
            "compare_message": compare_result["message"],
            "review_required": compare_result["status"] == "risk_increased",
            "saved_memory": [
                {"key": "previous_risk", "value": probability},
                {"key": "age", "value": features.get("age")},
            ],
        }
        return jsonify(response)

    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except FileNotFoundError as exc:
        return jsonify({"error": str(exc)}), 500
    except Exception as exc:
        return jsonify({"error": f"Prediction failed: {exc}"}), 500


@app.route("/chat", methods=["POST"])
def chat_endpoint():
    """Respond to user messages using AI-powered healthcare assistant."""
    try:
        payload = request.get_json(force=True)
        user_id = payload.get("user_id")
        message = payload.get("message")
        if not user_id or not message:
            return jsonify({"error": "Please include user_id and message in the request."}), 400

        # Get memory context for AI
        memory_context = {
            "name": _read_memory(user_id, "name"),
            "age": _read_memory(user_id, "age"),
            "symptoms": _read_memory(user_id, "symptoms"),
            "previous_risk": _read_memory(user_id, "previous_risk"),
        }
        
        # Get prediction if available
        prediction = _read_memory(user_id, "previous_risk")
        prediction_class = None
        if prediction is not None and isinstance(prediction, (int, float)):
            prediction_class = 1 if prediction > 0.5 else 0

        conversation_history = payload.get("history", [])
        if not isinstance(conversation_history, list):
            conversation_history = []
        
        # Generate AI response
        ai_response = generate_ai_response(
            message,
            prediction=prediction_class,
            memory_context=memory_context,
            conversation_history=conversation_history,
        )
        
        # Also run traditional chatbot for memory extraction
        response_payload = chatbot_response(message, user_id)
        
        # Replace response with AI-generated one
        response_payload["response"] = ai_response
        response_payload["ai_powered"] = True
        
        return jsonify(response_payload)
    except Exception as exc:
        print(f"Chat endpoint error: {exc}")
        return jsonify({"error": f"Chatbot failed: {exc}"}), 500


@app.route("/memory/<user_id>/<memory_key>", methods=["GET"])
def memory_lookup(user_id: str, memory_key: str):
    """Retrieve a specific memory entry for debugging or review."""
    result = get_memory(user_id, memory_key)
    if not result:
        return jsonify({"error": "Memory not found."}), 404
    return jsonify({"user_id": user_id, "key": memory_key, "value": result.value, "source": result.source})


@app.route("/chat-ai", methods=["POST"])
def chat_ai_endpoint():
    """Pure AI response endpoint without traditional memory extraction."""
    try:
        payload = request.get_json(force=True)
        user_id = payload.get("user_id")
        message = payload.get("message")
        prediction = payload.get("prediction")  # Optional: 0 or 1
        
        if not user_id or not message:
            return jsonify({"error": "Please include user_id and message in the request."}), 400
        
        # Get memory context
        memory_context = {
            "name": _read_memory(user_id, "name"),
            "age": _read_memory(user_id, "age"),
            "symptoms": _read_memory(user_id, "symptoms"),
            "previous_risk": _read_memory(user_id, "previous_risk"),
        }
        
        # Generate AI response
        ai_response = generate_ai_response(message, prediction=prediction, memory_context=memory_context)
        
        return jsonify({"response": ai_response, "user_id": user_id})
    except Exception as exc:
        print(f"AI chat endpoint error: {exc}")
        return jsonify({"error": f"AI chat failed: {exc}"}), 500


if __name__ == "__main__":
    print(f"OpenAI integration: {'✓ Enabled' if OPENAI_CLIENT else '✗ Disabled (set OPENAI_API_KEY)'}")
    app.run(debug=True, host="0.0.0.0", port=int(os.getenv("FLASK_PORT", 5000)))
