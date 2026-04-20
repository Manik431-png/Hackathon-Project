# OpenAI ChatGPT Integration - Quick Start

## Step 1: Install OpenAI Package
```bash
pip install openai
# OR
pip install -r requirements.txt
```

## Step 2: Get API Key
1. Go to: https://platform.openai.com/account/api-keys
2. Click "Create new secret key"
3. Copy the key (starts with `sk-`)

## Step 3: Set Environment Variable

**Create `.env` file in your project:**
```
OPENAI_API_KEY=sk-your-api-key-here
```

**OR set system variable:**
```bash
# Linux/Mac
export OPENAI_API_KEY=sk-your-api-key-here

# Windows PowerShell
$env:OPENAI_API_KEY="sk-your-api-key-here"
```

## Step 4: Start Flask Server
```bash
python flask_app.py
```

You should see:
```
OpenAI integration: ✓ Enabled
 * Running on http://127.0.0.1:5000
```

## Step 5: Test the Chat Endpoint

### Using curl:
```bash
curl -X POST http://127.0.0.1:5000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user-001",
    "message": "I have chest pain"
  }'
```

### Using Python:
```python
import requests

response = requests.post(
    "http://127.0.0.1:5000/chat",
    json={
        "user_id": "user-001",
        "message": "I have chest pain"
    }
)

print(response.json()["response"])
```

### Expected Response:
```json
{
  "response": "Chest pain is a serious symptom. Please seek immediate medical attention by calling 911 or visiting the nearest emergency room.",
  "ai_powered": true,
  "memory_actions": [...]
}
```

---

## Available Endpoints

### 1. `/chat` (Recommended)
**AI + Memory Extraction + Learning**

```bash
POST /chat
{
  "user_id": "user-001",
  "message": "I am 25 years old with fatigue"
}
```

**Response includes:**
- AI-generated response
- Memory extraction (age, symptoms)
- Learning from conversation

---

### 2. `/chat-ai` (Pure AI)
**AI Only (no memory extraction)**

```bash
POST /chat-ai
{
  "user_id": "user-001",
  "message": "What tests should I get?",
  "prediction": 0
}
```

**Response:**
```json
{
  "response": "For heart health, your doctor may recommend: ECG test, Blood Pressure monitoring, and Cholesterol panel.",
  "user_id": "user-001"
}
```

---

## What the AI Can Do

### ✓ High Risk (prediction=1)
```
"Your heart condition requires urgent evaluation. 
Please visit an emergency room or call 911 immediately."
```

### ✓ Low Risk (prediction=0)
```
"Your heart screening shows low risk. 
Maintain healthy habits and schedule regular check-ups."
```

### ✓ Symptom Recognition
Recognizes: chest pain, shortness of breath, dizziness, fatigue, palpitations, etc.

### ✓ Personalization
```
If memory has previous data:
"Earlier you mentioned chest pain. 
Combined with your age (25) and risk score (75%), 
please schedule a doctor's appointment."
```

### ✓ Medical Suggestions
- ECG test
- Blood Pressure monitoring
- Cholesterol panel
- Doctor consultation

---

## Example Conversation Flow

```
User: "My name is Raj"
AI: "Nice to meet you, Raj!"

User: "I'm 30 years old"
AI: "Got it! I've noted you are 30 years old. This helps me provide better health guidance."

User: "I have chest pain"
AI: "Chest pain can be serious. I recommend you see a doctor or visit the ER. 
Consider getting an ECG test to evaluate your heart health."

User: "Do I need tests?"
AI: "Based on your symptoms and age, yes. Ask your doctor about: 
ECG, Blood Pressure monitoring, and Cholesterol panel."
```

---

## Troubleshooting

### Problem: "OpenAI integration: ✗ Disabled"
```bash
# Check if OPENAI_API_KEY is set
echo $OPENAI_API_KEY

# If empty, set it:
export OPENAI_API_KEY=sk-your-key
python flask_app.py
```

### Problem: "Invalid API key provided"
- Go to: https://platform.openai.com/account/api-keys
- Generate new key
- Update `.env` file
- Restart server

### Problem: "Timeout"
The API took too long. Try again - may have high traffic.

### Problem: "Rate limited (429)"
You've exceeded rate limits. Wait a moment before retrying.

---

## Cost Estimate

| Messages/Day | Monthly Cost |
|---|---|
| 100 | ~$0.50 |
| 500 | ~$2.50 |
| 1,000 | ~$5.00 |
| 5,000 | ~$25 |

---

## Features Included

✓ AI-powered responses  
✓ Memory context awareness  
✓ High/Low risk handling  
✓ Symptom recognition  
✓ Medical test suggestions  
✓ Fallback messages  
✓ Error handling  
✓ Production-ready code  

---

## Next Steps

1. **Monitor API usage:** https://platform.openai.com/account/usage
2. **Integrate with Streamlit:** Check `app.py` for frontend
3. **Add more memory:** Store conversation history
4. **Customize responses:** Edit system prompt in `generate_ai_response()`

---

## Production Deployment

```bash
# Use gunicorn for production
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 flask_app:app
```

---

**Ready to go!** 🚀

Your healthcare chatbot now has AI superpowers! 💪
