from flask import Flask, request, jsonify
from flask_cors import CORS
import requests, os, time
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.json
    messages = data.get("messages")

    if not messages:
        return jsonify({"reply": "No message received"}), 400

   payload = {
        "model": "deepseek/deepseek-r1-0528:free",
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are Guru JI, a calm, wise AI guide created by Gururaj Achar. "
                    "Respond warmly, clearly, and in clean Markdown. Act like a t from teacher from karnataka. "
                    "Understand context from previous messages. Dont give the responce in any other languages except English and Kannada. "
                )
            },
            *messages
        ]
    }

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }

    for _ in range(3):
        try:
            res = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=60
            )
            if res.status_code == 200:
                reply = res.json()["choices"][0]["message"]["content"]
                return jsonify({"reply": reply})
            time.sleep(4)
        except:
            time.sleep(4)

    return jsonify({"reply": "⏳ Guru JI is waking up… try again."})
