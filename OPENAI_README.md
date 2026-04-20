# 🤖 OpenAI ChatGPT Integration for Healthcare Chatbot

> AI-powered heart disease prediction assistant with OpenAI GPT-4o-mini

## ✨ What's Included

✅ **AI-Powered Responses** - Uses OpenAI GPT-4o-mini for intelligent replies  
✅ **Symptom Recognition** - Understands chest pain, shortness of breath, dizziness, etc.  
✅ **Risk-Aware** - Different responses for HIGH/LOW risk predictions  
✅ **Personalized** - Uses patient memory (name, age, symptoms, history)  
✅ **Medical Suggestions** - Recommends ECG, BP tests, cholesterol tests  
✅ **Fallback System** - Works even if API fails  
✅ **Production Ready** - Error handling, logging, timeouts included  
✅ **Easy Setup** - 5-minute configuration  

---

## 🚀 Quick Start (5 Minutes)

### 1️⃣ Install Dependencies
```bash
pip install -r requirements.txt
```

### 2️⃣ Get OpenAI API Key
Visit: https://platform.openai.com/account/api-keys
- Create new secret key
- Copy the key (starts with `sk-`)

### 3️⃣ Set Environment Variable
```bash
# Create .env file
echo 'OPENAI_API_KEY=sk-your-key-here' > .env
```

### 4️⃣ Start Flask Server
```bash
python flask_app.py
```

**Should show:**
```
OpenAI integration: ✓ Enabled
 * Running on http://127.0.0.1:5000
```

### 5️⃣ Test It!
```bash
curl -X POST http://localhost:5000/chat \
  -H "Content-Type: application/json" \
  -d '{"user_id": "user-001", "message": "I have chest pain"}'
```

**Response:**
```json
{
  "response": "Chest pain is serious. Please seek immediate medical attention or call 911.",
  "ai_powered": true
}
```

---

## 📚 Documentation

| File | Purpose |
|------|---------|
| **OPENAI_QUICK_START.md** | 📖 Setup guide (you are here) |
| **OPENAI_INTEGRATION_GUIDE.md** | 📚 Complete reference |
| **OPENAI_CODE_EXAMPLES.md** | 💻 Code patterns & examples |
| **OPENAI_INTEGRATION_SUMMARY.md** | 📋 Implementation details |

---

## 🎯 Key Features

### 1. Smart Symptom Recognition
The AI recognizes and responds appropriately to:
- ❤️ Chest pain / tightness / pressure
- 😮‍💨 Shortness of breath
- 😵 Dizziness / fainting
- 💓 Palpitations / racing heart
- 😴 Fatigue
- 🤢 Nausea / vomiting
- 💦 Excessive sweating

### 2. Risk-Based Responses

#### 🔴 HIGH RISK (prediction=1)
```
Chest pain and shortness of breath are serious symptoms.
Please seek immediate medical attention or call 911.
```

#### 🟢 LOW RISK (prediction=0)
```
Your screening shows low risk. Continue healthy habits 
and schedule regular check-ups with your doctor.
```

### 3. Personalized Responses
```
Earlier you mentioned chest pain.
Based on your age (45) and previous risk (75%),
please schedule a doctor's appointment right away.
```

### 4. Medical Recommendations
```
Ask your doctor about these tests:
- ECG (electrocardiogram)
- Blood Pressure monitoring
- Cholesterol panel
```

---

## 📡 API Endpoints

### POST `/chat` (Recommended)
AI-powered response with automatic memory extraction

```bash
curl -X POST http://localhost:5000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user-001",
    "message": "I am 30 years old with chest pain"
  }'
```

**Response:**
```json
{
  "response": "Chest pain at any age is serious...",
  "ai_powered": true,
  "memory_actions": [
    {"key": "age", "value": 30},
    {"key": "symptoms", "value": ["chest pain"]}
  ]
}
```

### POST `/chat-ai` (Pure AI)
Pure AI response without memory extraction (optional)

```bash
curl -X POST http://localhost:5000/chat-ai \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user-001",
    "message": "What tests should I get?",
    "prediction": 0
  }'
```

---

## 🔧 Configuration

### Environment Variables (.env)

```env
# OpenAI API Key (REQUIRED)
OPENAI_API_KEY=sk-your-key-here

# Hindsight Memory (Optional)
HINDSIGHT_API_KEY=your-hindsight-key

# Flask Port (Optional)
FLASK_PORT=5000
```

### Tune AI Response

Edit `flask_app.py` in `generate_ai_response()`:

```python
# Model selection
OPENAI_MODEL = "gpt-4o-mini"  # Current (fast, cheap)
# OPENAI_MODEL = "gpt-4"      # Alternative (powerful)

# Response settings
temperature=0.7,    # 0=focused, 1=creative
max_tokens=150,     # Response length
timeout=10          # Seconds
```

---

## 💡 Usage Examples

### Python
```python
import requests

response = requests.post(
    "http://localhost:5000/chat",
    json={
        "user_id": "user-001",
        "message": "I have chest pain"
    }
)

print(response.json()["response"])
# Output: "Chest pain is serious. Please seek immediate..."
```

### JavaScript/Node.js
```javascript
fetch('http://localhost:5000/chat', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    user_id: 'user-001',
    message: 'I have dizziness'
  })
})
.then(r => r.json())
.then(data => console.log(data.response));
```

### cURL
```bash
# Simple query
curl -X POST http://localhost:5000/chat \
  -H "Content-Type: application/json" \
  -d '{"user_id": "user-001", "message": "hello"}'

# With risk prediction
curl -X POST http://localhost:5000/chat-ai \
  -H "Content-Type: application/json" \
  -d '{"user_id": "user-001", "message": "Am I okay?", "prediction": 1}'
```

---

## 🧪 Testing

### Verify Installation
```bash
# Check OpenAI package
python -c "from openai import OpenAI; print('✓ Installed')"

# Check Flask
python -c "import flask; print('✓ Installed')"
```

### Test Syntax
```bash
python -m py_compile flask_app.py && echo "✓ Syntax OK"
```

### Test Endpoint
```bash
# Start server in background
python flask_app.py &

# Wait 2 seconds
sleep 2

# Test
curl -X POST http://localhost:5000/chat \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "message": "hello"}'
```

---

## 💰 Cost Breakdown

**Model:** gpt-4o-mini (most economical)

| Volume | Input Cost | Output Cost | Monthly |
|--------|-----------|-----------|---------|
| 100 msgs/day | $0.075 | $0.30 | ~$0.50 |
| 500 msgs/day | $0.375 | $1.50 | ~$2.50 |
| 1,000 msgs/day | $0.75 | $3.00 | ~$5.00 |
| 5,000 msgs/day | $3.75 | $15.00 | ~$25.00 |

**Per message: ~$0.0012**

---

## 🐛 Troubleshooting

### Problem: "OpenAI integration: ✗ Disabled"
**Solution:** Set API key
```bash
export OPENAI_API_KEY=sk-your-key
python flask_app.py
```

### Problem: "Invalid API key provided"
**Solution:** 
1. Go to https://platform.openai.com/account/api-keys
2. Create new key
3. Update `.env` file
4. Restart server

### Problem: "Rate limited (429)"
**Solution:** Wait a moment and retry (you've hit rate limits)

### Problem: "Timeout"
**Solution:** API took too long (will retry automatically)

### Problem: "Module not found: openai"
**Solution:** 
```bash
pip install openai
# or
pip install -r requirements.txt
```

---

## 🔒 Security Best Practices

✓ **DO:**
- Use environment variables for API keys
- Store `.env` in `.gitignore`
- Rotate API keys regularly
- Monitor usage at https://platform.openai.com/account/usage

✗ **DON'T:**
- Hardcode API keys
- Commit `.env` to Git
- Share API keys
- Use API key in frontend code

---

## 📊 Real-World Conversation

```
User: My name is Raj
AI: Nice to meet you, Raj!

User: I'm 35 years old
AI: Got it! I've noted you are 35 years old. This helps me provide better health guidance.

User: I have chest pain and shortness of breath
AI: Chest pain and shortness of breath are serious symptoms. 
Please seek immediate medical attention or call 911.
(Memory: stored symptoms, predicting HIGH RISK)

User: Should I see a doctor?
AI: Yes, absolutely. Your symptoms require urgent evaluation.
Your doctor may recommend ECG, Blood Pressure monitoring, and Cholesterol panel.

User: What do you remember about me?
AI: I remember: Name: Raj; Age: 35; Symptoms: chest pain, shortness of breath.
```

---

## 🚀 Deployment

### Local Development
```bash
python flask_app.py
# Runs on http://localhost:5000
```

### Production (Gunicorn)
```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 flask_app:app
```

### Docker (Optional)
```dockerfile
FROM python:3.10
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:5000", "flask_app:app"]
```

---

## 📈 Monitoring & Analytics

**Check API Usage:**
```
https://platform.openai.com/account/usage
```

**Monitor Costs:**
- Daily spending estimate
- Token usage breakdown
- Rate limit status

**Add Logging (Optional):**
```python
import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# In /chat endpoint:
logger.info(f"User: {user_id} | Message: {message} | Response: {response}")
```

---

## ✅ Implementation Checklist

- [x] OpenAI package installed
- [x] API key obtained
- [x] `.env` file created
- [x] Flask server running
- [x] Shows "✓ Enabled" message
- [x] `/chat` endpoint responds
- [x] `/chat-ai` endpoint works
- [x] Responses are personalized
- [x] Memory is stored
- [x] Error handling works

---

## 📞 Support

**Having Issues?**

1. Check API key: https://platform.openai.com/account/api-keys
2. Verify `.env` file exists
3. Restart Flask server
4. Check OpenAI status: https://status.openai.com
5. Review error logs in console

**Documentation:**
- `OPENAI_QUICK_START.md` - This file
- `OPENAI_INTEGRATION_GUIDE.md` - Full reference
- `OPENAI_CODE_EXAMPLES.md` - Code patterns

---

## 🎉 What's Next?

### Immediate (Today)
✓ Setup complete  
✓ Test endpoints  
✓ Monitor first interactions  

### This Week
- Integrate with Streamlit frontend
- Add conversation logging
- Set up usage monitoring

### This Month
- Fine-tune response templates
- Add more medical context
- Create admin dashboard

### Later
- Add multi-language support
- Implement context history
- Deploy to production

---

## 📝 License

This integration uses OpenAI's API. Subject to:
- OpenAI Terms of Service
- Your local healthcare regulations
- Data privacy laws (GDPR, CCPA, HIPAA)

---

## 🙏 Credits

**Built with:**
- 🧠 OpenAI GPT-4o-mini
- 🔧 Flask
- 📊 Streamlit
- 💾 Hindsight Memory API

---

## Version Info

| Item | Value |
|------|-------|
| Version | 1.0 |
| Release Date | April 20, 2026 |
| Status | ✓ Production Ready |
| Support | Active |

---

## 🤝 Contributing

Have ideas or found issues?
- Check documentation first
- Test with latest version
- Report bugs with details

---

## 🎯 Success!

Your healthcare chatbot now has **AI superpowers**! 🚀

Start the server and ask: *"What should I know about heart health?"*

---

**Questions?** See the other documentation files or visit:
- https://platform.openai.com/docs
- https://github.com/openai/openai-python
- https://community.openai.com

**Happy coding!** ✨
