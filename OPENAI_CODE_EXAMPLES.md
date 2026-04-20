# OpenAI Integration - Code Examples

## Table of Contents
1. [Function Signature](#function-signature)
2. [Basic Usage](#basic-usage)
3. [Flask Route Integration](#flask-route-integration)
4. [Advanced Examples](#advanced-examples)
5. [Error Handling](#error-handling)

---

## Function Signature

```python
def generate_ai_response(
    user_input: str, 
    prediction: Optional[int] = None, 
    memory_context: Optional[Dict[str, Any]] = None
) -> str:
    """
    Generate AI-powered healthcare response.
    
    Args:
        user_input (str): Patient's message
        prediction (int, optional): 0=LOW RISK, 1=HIGH RISK
        memory_context (dict, optional): 
            {
                "name": str,
                "age": int,
                "symptoms": list,
                "previous_risk": float
            }
    
    Returns:
        str: AI response text
    """
```

---

## Basic Usage

### Example 1: Simple Query
```python
from flask_app import generate_ai_response

# No context, no prediction
response = generate_ai_response("Do I have heart disease?")
print(response)
# Output: "I cannot diagnose heart disease, but I can help..."
```

### Example 2: With Symptoms
```python
response = generate_ai_response("I have chest pain and dizziness")
print(response)
# Output: "Chest pain and dizziness are serious symptoms..."
```

### Example 3: With Risk Level
```python
# HIGH RISK
response = generate_ai_response(
    "Should I be worried?",
    prediction=1
)
print(response)
# Output: "Your heart health needs immediate attention..."

# LOW RISK
response = generate_ai_response(
    "Should I be worried?",
    prediction=0
)
print(response)
# Output: "Your screening shows low risk. Continue..."
```

---

## Flask Route Integration

### Implementation in `/chat` Endpoint

```python
@app.route("/chat", methods=["POST"])
def chat_endpoint():
    """Respond to user messages using AI-powered assistant."""
    try:
        payload = request.get_json(force=True)
        user_id = payload.get("user_id")
        message = payload.get("message")
        
        if not user_id or not message:
            return jsonify({"error": "Missing user_id or message"}), 400

        # Step 1: Gather memory context
        memory_context = {
            "name": _read_memory(user_id, "name"),
            "age": _read_memory(user_id, "age"),
            "symptoms": _read_memory(user_id, "symptoms"),
            "previous_risk": _read_memory(user_id, "previous_risk"),
        }
        
        # Step 2: Get risk prediction
        prediction = _read_memory(user_id, "previous_risk")
        prediction_class = None
        if prediction and isinstance(prediction, (int, float)):
            prediction_class = 1 if prediction > 0.5 else 0
        
        # Step 3: Generate AI response
        ai_response = generate_ai_response(
            message,
            prediction=prediction_class,
            memory_context=memory_context
        )
        
        # Step 4: Extract and store information
        response_payload = chatbot_response(message, user_id)
        
        # Step 5: Use AI response
        response_payload["response"] = ai_response
        response_payload["ai_powered"] = True
        
        return jsonify(response_payload)
    
    except Exception as exc:
        print(f"Error: {exc}")
        return jsonify({"error": str(exc)}), 500
```

---

## Advanced Examples

### Example 1: Risk Assessment Response

```python
def assess_heart_health(user_id: str, symptoms: List[str], age: int):
    """Assess heart health and provide recommendation."""
    
    # Create memory context
    memory = {
        "name": _read_memory(user_id, "name"),
        "age": age,
        "symptoms": symptoms,
        "previous_risk": _read_memory(user_id, "previous_risk")
    }
    
    # Determine risk level
    serious_symptoms = ["chest pain", "shortness of breath", "fainting"]
    has_serious = any(s in symptoms for s in serious_symptoms)
    prediction = 1 if has_serious else 0
    
    # Build prompt
    symptom_text = ", ".join(symptoms)
    message = f"I'm a {age} year old with {symptom_text}"
    
    # Get AI response
    response = generate_ai_response(
        message,
        prediction=prediction,
        memory_context=memory
    )
    
    return response
```

**Usage:**
```python
result = assess_heart_health(
    user_id="user-001",
    symptoms=["chest pain", "fatigue"],
    age=45
)
print(result)
```

---

### Example 2: Conversation with History

```python
class HealthChatSession:
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.conversation = []
        self.memory = self._load_memory()
    
    def _load_memory(self):
        return {
            "name": _read_memory(self.user_id, "name"),
            "age": _read_memory(self.user_id, "age"),
            "symptoms": _read_memory(self.user_id, "symptoms"),
            "previous_risk": _read_memory(self.user_id, "previous_risk"),
        }
    
    def send_message(self, message: str, prediction=None) -> str:
        # Get AI response
        response = generate_ai_response(
            message,
            prediction=prediction,
            memory_context=self.memory
        )
        
        # Store in history
        self.conversation.append({
            "user": message,
            "assistant": response
        })
        
        return response
    
    def get_history(self):
        return self.conversation
```

**Usage:**
```python
session = HealthChatSession("user-001")

r1 = session.send_message("I'm 30 years old")
print(r1)

r2 = session.send_message("I have chest pain")
print(r2)

print(session.get_history())
```

---

### Example 3: Batch Processing

```python
def process_multiple_patients(patients: List[Dict]) -> List[Dict]:
    """Process multiple patient messages."""
    results = []
    
    for patient in patients:
        user_id = patient["user_id"]
        message = patient["message"]
        prediction = patient.get("prediction")
        
        memory_context = {
            "name": _read_memory(user_id, "name"),
            "age": _read_memory(user_id, "age"),
            "symptoms": _read_memory(user_id, "symptoms"),
            "previous_risk": _read_memory(user_id, "previous_risk"),
        }
        
        response = generate_ai_response(
            message,
            prediction=prediction,
            memory_context=memory_context
        )
        
        results.append({
            "user_id": user_id,
            "response": response,
            "timestamp": datetime.now()
        })
    
    return results
```

---

## Error Handling

### Example 1: Try-Except Pattern

```python
def safe_get_ai_response(user_input: str, user_id: str = None) -> str:
    """Get AI response with error handling."""
    try:
        memory = None
        if user_id:
            memory = {
                "name": _read_memory(user_id, "name"),
                "age": _read_memory(user_id, "age"),
                "symptoms": _read_memory(user_id, "symptoms"),
                "previous_risk": _read_memory(user_id, "previous_risk"),
            }
        
        response = generate_ai_response(user_input, memory_context=memory)
        return response
    
    except Exception as e:
        print(f"Error generating response: {e}")
        return "I'm temporarily unavailable. Please consult a healthcare professional."
```

---

### Example 2: Retry Logic

```python
import time
from typing import Optional

def get_ai_response_with_retry(
    user_input: str,
    max_retries: int = 3,
    timeout: int = 1
) -> Optional[str]:
    """Get AI response with retry logic."""
    
    for attempt in range(max_retries):
        try:
            response = generate_ai_response(user_input)
            return response
        
        except Exception as e:
            print(f"Attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                time.sleep(timeout)
            else:
                print("Max retries reached")
                return None
```

---

### Example 3: Timeout Handling

```python
import signal

def timeout_handler(signum, frame):
    raise TimeoutError("AI response took too long")

def get_ai_response_with_timeout(user_input: str, timeout_sec: int = 5) -> str:
    """Get AI response with timeout."""
    
    # Set signal handler
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(timeout_sec)
    
    try:
        response = generate_ai_response(user_input)
        signal.alarm(0)  # Disable alarm
        return response
    
    except TimeoutError:
        return "Response took too long. Please try again."
```

---

## Testing the Integration

### Unit Test

```python
import unittest
from flask_app import generate_ai_response

class TestAIResponse(unittest.TestCase):
    
    def test_simple_response(self):
        """Test basic AI response."""
        response = generate_ai_response("Hello")
        self.assertIsInstance(response, str)
        self.assertGreater(len(response), 0)
    
    def test_high_risk_response(self):
        """Test HIGH RISK prediction."""
        response = generate_ai_response(
            "Should I worry?",
            prediction=1
        )
        # Should contain urgent language
        self.assertIn("immediate", response.lower())
    
    def test_low_risk_response(self):
        """Test LOW RISK prediction."""
        response = generate_ai_response(
            "Am I okay?",
            prediction=0
        )
        # Should contain positive language
        self.assertTrue(len(response) > 0)
    
    def test_with_memory_context(self):
        """Test with memory context."""
        memory = {
            "name": "John",
            "age": 45,
            "symptoms": ["chest pain"],
            "previous_risk": 0.75
        }
        response = generate_ai_response(
            "What should I do?",
            memory_context=memory
        )
        self.assertIsInstance(response, str)

if __name__ == "__main__":
    unittest.main()
```

**Run tests:**
```bash
python -m unittest test_flask_app.TestAIResponse
```

---

## Integration Checklist

- [x] OpenAI package installed
- [x] API key set in `.env`
- [x] Function added to flask_app.py
- [x] `/chat` endpoint updated
- [x] `/chat-ai` endpoint added
- [x] Error handling implemented
- [x] Requirements.txt updated
- [x] Code syntax verified
- [x] Documentation created

---

## Performance Tips

1. **Cache responses** for common questions
2. **Batch API calls** when possible
3. **Use lower temperature** (0.5-0.7) for consistency
4. **Limit tokens** to 150 for faster responses
5. **Monitor API usage** at https://platform.openai.com/account/usage

---

## Security Best Practices

```python
# ✓ Good: Using environment variable
import os
api_key = os.getenv("OPENAI_API_KEY")

# ✗ Bad: Hardcoding API key
api_key = "sk-..." # NEVER do this!

# ✓ Good: Use .env file
from dotenv import load_dotenv
load_dotenv()

# ✗ Bad: Committing .env to Git
# Add to .gitignore:
# .env
# *.pyc
```

---

## Monitoring & Logging

```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def log_ai_call(user_id: str, user_input: str, response: str):
    """Log AI interactions."""
    logger.info(f"User: {user_id} | Input: {user_input} | Response: {response[:50]}...")

# Usage
response = generate_ai_response(message)
log_ai_call(user_id, message, response)
```

---

**Ready to deploy!** 🚀

For production use, ensure:
- API key stored securely
- Error logging enabled
- Rate limiting implemented
- Monitoring active
- Backup communication plan ready
