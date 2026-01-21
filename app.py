from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import os
import time
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# In-memory conversation store (simple & effective)
conversation_history = []

@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "Guru JI backend"}), 200


@app.route("/api/chat", methods=["POST"])
def chat():
    global conversation_history

    data = request.get_json()
    user_message = data.get("message")

    if not user_message:
        return jsonify({"error": "No message provided"}), 400

    # Add user message to memory
    conversation_history.append({
        "role": "user",
        "content": user_message
    })

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": "deepseek/deepseek-r1-0528:free",
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are Guru JI, an AI created by Gururaj Achar. "
                    "You remember the full conversation. "
                    "Reply in clean Markdown. "
                    "Keep answers short, calm, and clear."
                )
            },
            *conversation_history
        ]
    }

    retries = 4

    for _ in range(retries):
        try:
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=70
            )

            if response.status_code == 200:
                result = response.json()
                ai_reply = result["choices"][0]["message"]["content"]

                # Save AI reply to memory
                conversation_history.append({
                    "role": "assistant",
                    "content": ai_reply
                })

                # Prevent memory overflow
                if len(conversation_history) > 12:
                    conversation_history = conversation_history[-10:]

                return jsonify({"reply": ai_reply})

            if response.status_code == 429:
                time.sleep(6)
                continue

            time.sleep(4)

        except requests.exceptions.RequestException:
            time.sleep(4)

    return jsonify({
        "reply": "⚠️ Guru JI is currently busy. Please try again in a moment."
    }), 200


