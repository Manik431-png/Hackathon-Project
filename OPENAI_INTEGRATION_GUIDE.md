# OpenAI ChatGPT Integration Guide

## Overview
This guide explains how to use the integrated OpenAI ChatGPT API in your healthcare chatbot. The AI generates intelligent, context-aware responses for heart health discussions.

---

## Setup Instructions

### 1. Install OpenAI Package
```bash
pip install openai
```

Or install from requirements.txt:
```bash
pip install -r requirements.txt
```

### 2. Get OpenAI API Key
- Visit: https://platform.openai.com/account/api-keys
- Create a new API key
- Copy the key

### 3. Set Environment Variable
Create or update `.env` file:
```
OPENAI_API_KEY=sk-your-api-key-here
```

Or set as system environment variable:
```bash
# Linux/Mac
export OPENAI_API_KEY=sk-your-api-key-here

# Windows PowerShell
$env:OPENAI_API_KEY="sk-your-api-key-here"
```

### 4. Verify Setup
```python
python -c "from openai import OpenAI; print('✓ OpenAI package installed')"
```

---

## Function Reference

### `generate_ai_response(user_input, prediction=None, memory_context=None)`

**Purpose:** Generate AI-powered healthcare assistant responses

**Parameters:**
- `user_input` (str): User's message
- `prediction` (int, optional): Heart disease prediction (0=LOW RISK, 1=HIGH RISK)
- `memory_context` (dict, optional): User's stored information
  - `name`: User's name
  - `age`: User's age
  - `symptoms`: List of reported symptoms
  - `previous_risk`: Previous risk score (0-1)

**Returns:** 
- str: AI-generated response

**Example:**
```python
from flask_app import generate_ai_response

# Simple usage
response = generate_ai_response("I have chest pain")
print(response)

# With medical context
memory = {
    "name": "Manik Kumar",
    "age": 20,
    "symptoms": ["chest pain", "shortness of breath"],
    "previous_risk": 0.75
}
response = generate_ai_response(
    "Should I see a doctor?",
    prediction=1,  # HIGH RISK
    memory_context=memory
)
print(response)
```

---

## API Endpoints

### Endpoint 1: `/chat` (AI-Powered)
Enhanced endpoint with AI responses + memory extraction.

**URL:** `POST http://localhost:5000/chat`

**Request Body:**
```json
{
  "user_id": "user-001",
  "message": "I have chest pain and shortness of breath"
}
```

**Response:**
```json
{
  "response": "Chest pain and shortness of breath are serious symptoms. Please seek immediate medical attention or call emergency services right away.",
  "ai_powered": true,
  "memory_actions": [
    {"key": "symptoms", "value": ["chest pain", "shortness of breath"]}
  ]
}
```

### Endpoint 2: `/chat-ai` (Pure AI Only)
Optional endpoint for AI responses without memory extraction.

**URL:** `POST http://localhost:5000/chat-ai`

**Request Body:**
```json
{
  "user_id": "user-001",
  "message": "What tests should I get?",
  "prediction": 0
}
```

**Response:**
```json
{
  "response": "For heart health screening, consider: ECG test, Blood Pressure monitoring, and Cholesterol panel. Schedule an appointment with your doctor to discuss which tests are appropriate for you.",
  "user_id": "user-001"
}
```

---

## Usage Examples

### Example 1: Basic Chat
```bash
curl -X POST http://127.0.0.1:5000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user123",
    "message": "I feel dizzy and my heart is racing"
  }'
```

### Example 2: With Risk Prediction
```bash
curl -X POST http://localhost:5000/chat-ai \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user123",
    "message": "Should I be worried?",
    "prediction": 1
  }'
```

### Example 3: Python Script
```python
import requests

url = "http://localhost:5000/chat"
payload = {
    "user_id": "user-001",
    "message": "I have chest pain"
}

response = requests.post(url, json=payload)
data = response.json()
print(data["response"])
```

---

## AI Response Behavior

### High Risk (prediction=1)
**Scenario:** User has HIGH risk score  
**Tone:** URGENT  
**Response Format:** Immediate doctor/ER recommendation

**Example:**
```
Your heart health needs immediate attention. Please consult a doctor or visit the ER right away.
```

### Low Risk (prediction=0)
**Scenario:** User has LOW risk score  
**Tone:** CALM + PREVENTIVE  
**Response Format:** Positive with advice

**Example:**
```
Based on screening, your heart risk is low. Continue healthy habits and schedule regular check-ups.
```

### Symptom Recognition
The AI recognizes and responds to:
- ✓ Chest pain / tightness
- ✓ Shortness of breath
- ✓ Dizziness / fainting
- ✓ Palpitations
- ✓ Fatigue
- ✓ Nausea
- ✓ Sweating

---

## System Prompt

The AI uses this system prompt for healthcare guidance:

```
You are a compassionate and knowledgeable healthcare AI assistant 
specializing in heart health.

Guidelines:
- For serious symptoms → STRONGLY recommend doctor/ER
- For mild symptoms → suggest doctor's appointment
- Mention tests: ECG, Blood Pressure, Cholesterol panel
- Keep responses SHORT (2-3 sentences max)
- Use simple language
- Be warm and professional
- Always encourage medical consultation
```

---

## Fallback Behavior

If OpenAI API fails, the bot returns safe fallback messages:

**HIGH RISK:**
```
Your heart health needs immediate attention. 
Please consult a doctor or visit the ER right away.
```

**LOW RISK:**
```
Based on screening, your heart risk is low. 
Continue healthy habits and schedule regular check-ups.
```

**NO PREDICTION:**
```
Please describe your symptoms in detail. 
Consider scheduling a doctor's appointment for evaluation.
```

---

## Configuration

### Model Selection
Default: `gpt-4o-mini` (cost-effective, fast)

To change model, edit `flask_app.py`:
```python
OPENAI_MODEL = "gpt-4o"  # More capable but slower
```

### Response Settings
Located in `generate_ai_response()`:
```python
response = OPENAI_CLIENT.chat.completions.create(
    model=OPENAI_MODEL,
    temperature=0.7,        # 0-1: Lower=more focused, Higher=more creative
    max_tokens=150,         # Maximum response length
    timeout=10              # API timeout in seconds
)
```

---

## Troubleshooting

### Issue 1: "OpenAI integration: ✗ Disabled"
**Solution:** Set `OPENAI_API_KEY` environment variable
```bash
export OPENAI_API_KEY=sk-your-key
python flask_app.py
```

### Issue 2: "APIError: Invalid API key"
**Solution:** Check your API key in `.env`
```bash
cat .env | grep OPENAI_API_KEY
```

### Issue 3: Response Timeout
**Solution:** Increase timeout in `generate_ai_response()`:
```python
timeout=20  # Increase from 10 to 20 seconds
```

### Issue 4: Rate Limiting
**Solution:** OpenAI has rate limits. If getting 429 errors:
- Wait a moment before retrying
- Upgrade your OpenAI plan if needed

---

## Cost Estimation

**Model:** gpt-4o-mini (economical)

| Usage | Approx. Cost |
|-------|-------------|
| 100 messages/day | ~$0.50/month |
| 1,000 messages/day | ~$5/month |
| 10,000 messages/day | ~$50/month |

---

## Best Practices

### 1. Always Include Memory Context
```python
memory_context = {
    "name": _read_memory(user_id, "name"),
    "age": _read_memory(user_id, "age"),
    "symptoms": _read_memory(user_id, "symptoms"),
    "previous_risk": _read_memory(user_id, "previous_risk"),
}
response = generate_ai_response(message, memory_context=memory_context)
```

### 2. Handle Errors Gracefully
```python
try:
    response = generate_ai_response(user_input)
except Exception as e:
    response = "I'm unavailable. Please consult a doctor."
```

### 3. Log API Calls (optional)
```python
print(f"User: {user_input}")
print(f"AI Response: {ai_response}")
```

### 4. Monitor Costs
```bash
# Check OpenAI usage dashboard
# https://platform.openai.com/account/usage
```

---

## Integration with Streamlit

The Streamlit app (`app.py`) now uses this AI backend:

```python
# In Health Chat tab
response = requests.post(
    "http://127.0.0.1:5000/chat-ai",
    json={"user_id": user_id, "message": chat_input}
)
```

---

## Security Notes

⚠️ **IMPORTANT:**
1. Never commit API keys to version control
2. Use `.env` file for local development
3. Use environment variables in production
4. Rotate API keys regularly
5. Monitor OpenAI dashboard for unusual activity

---

## Support

For issues:
1. Check OpenAI status: https://status.openai.com
2. Review error logs in console
3. Test API key: `openai api completions.create -m gpt-4o-mini -p "test"`

---

## Example Conversational Flow

```
User: "I have chest pain"
→ AI: "Chest pain is serious. Please see a doctor immediately or call 911 if severe."

User: "What tests should I get?"
→ AI: "Your doctor may recommend ECG, Blood Pressure monitoring, and Cholesterol panel based on your symptoms."

User: "How's my heart health?"
→ AI: "Based on your previous assessment, continue monitoring your symptoms and follow your doctor's advice. Schedule check-ups as recommended."

User: "Remember my age?"
→ AI: "Yes, I remember you are 20 years old. At your age, these symptoms are unusual - please get checked out by a professional."
```

---

**Last Updated:** April 2026  
**Version:** 1.0  
**Status:** Production Ready ✓
