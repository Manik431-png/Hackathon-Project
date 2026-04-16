from flask import Flask, render_template, request
import numpy as np
import pickle

app = Flask(__name__)

# Load model
model = pickle.load(open("model.pkl", "rb"))

# ---------------- CHATBOT ----------------
def chatbot_response(query):
    query = query.lower()

    if "diet" in query:
        return "Eat fruits, vegetables, avoid oily food."
    elif "exercise" in query:
        return "Do 30 minutes walking daily."
    elif "heart" in query:
        return "Maintain healthy lifestyle and regular checkup."
    else:
        return "Sorry, I didn't understand. Ask about diet or exercise."


@app.route("/chat", methods=["POST"])
def chat():
    user_input = request.form["message"]
    reply = chatbot_response(user_input)
    return reply


# ---------------- AI AGENT ----------------
def agent_decision(prediction):
    if prediction == 1:
        return "⚠️ High Risk! Please consult a doctor immediately. Avoid oily food & exercise daily."
    else:
        return "✅ Low Risk! Maintain healthy lifestyle and regular exercise."


# ---------------- ROUTES ----------------
@app.route("/")
def home():
    return render_template("index.html")


@app.route("/predict", methods=["POST"])
def predict():
    try:
        features = [
            float(request.form['age']),
            float(request.form['sex']),   # ✅ FIXED
            float(request.form['cp']),
            float(request.form['trestbps']),
            float(request.form['chol']),
            float(request.form['fbs']),
            float(request.form['restecg']),
            float(request.form['thalach']),
            float(request.form['exang']),
            float(request.form['oldpeak']),
            float(request.form['slope']),
            float(request.form['ca']),
            float(request.form['thal'])
        ]

        final = np.array(features).reshape(1, -1)

        prediction = model.predict(final)[0]
        result = agent_decision(prediction)

        return render_template("index.html", prediction_text=result)

    except:
        return render_template("index.html", prediction_text="Error in input")


if __name__ == "__main__":
    app.run(debug=True)