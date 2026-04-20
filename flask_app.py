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

from assistant_memory import get_memory, save_memory, update_memory, MemoryResult

load_dotenv()

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


def chatbot_response(message: str, user_id: str) -> Dict[str, Any]:
    """Generate a chatbot response using persistent Hindsight memory."""
    normalized = message.strip()
    response_text = _build_personalized_greeting(user_id)
    details = {"memory_actions": []}

    name = _safe_extract_name(normalized)
    if name:
        _store_user_attribute(user_id, "name", name)
        details["memory_actions"].append({"key": "name", "value": name})
        return {
            "response": f"Nice to meet you, {name}. I will remember your name for future chat sessions.",
            "details": details,
        }

    if re.search(r"what is my name|who am i|do you know my name", normalized, re.IGNORECASE):
        stored_name = _read_memory(user_id, "name")
        if stored_name:
            return {"response": f"Your name is {stored_name}.", "details": details}
        return {"response": "I don't have your name yet. Please tell me your name so I can remember it.", "details": details}

    symptoms = _find_symptoms(normalized)
    if symptoms:
        existing_symptoms = _read_memory(user_id, "symptoms") or []
        merged = _merge_symptom_lists(existing_symptoms, symptoms)
        _store_user_attribute(user_id, "symptoms", merged)
        details["memory_actions"].append({"key": "symptoms", "value": merged})
        symptom_text = ", ".join(merged)
        return {
            "response": f"I've noted your symptoms: {symptom_text}. If you want, I can also help you compare your most recent risk result.",
            "details": details,
        }

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

    if re.search(r"hello|hi|hey|good morning|good evening", normalized, re.IGNORECASE):
        name = _read_memory(user_id, "name")
        if name:
            return {"response": f"Hello again, {name}! How can I help with your heart wellness today?", "details": details}
        return {"response": "Hello! I'm your AI Health Assistant. What would you like to do today?", "details": details}

    return {
        "response": response_text,
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
    """Respond to user messages using chatbot memory."""
    try:
        payload = request.get_json(force=True)
        user_id = payload.get("user_id")
        message = payload.get("message")
        if not user_id or not message:
            return jsonify({"error": "Please include user_id and message in the request."}), 400

        response_payload = chatbot_response(message, user_id)
        return jsonify(response_payload)
    except Exception as exc:
        return jsonify({"error": f"Chatbot failed: {exc}"}), 500


@app.route("/memory/<user_id>/<memory_key>", methods=["GET"])
def memory_lookup(user_id: str, memory_key: str):
    """Retrieve a specific memory entry for debugging or review."""
    result = get_memory(user_id, memory_key)
    if not result:
        return jsonify({"error": "Memory not found."}), 404
    return jsonify({"user_id": user_id, "key": memory_key, "value": result.value, "source": result.source})


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.getenv("FLASK_PORT", 5000)))
