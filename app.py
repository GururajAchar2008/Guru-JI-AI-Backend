from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
# Allow CORS for your frontend (Render or localhost)
CORS(app)

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "Guru JI backend"}), 200

@app.route("/api/chat", methods=["POST"])
def chat():
    messages = request.json.get("messages")

    if not message:
        return jsonify({"error": "No message provided"}), 400

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
                "Reply in clean Markdown. Keep answers short and clear."
            )
        },
        *messages
      ]
   }


    # 🔁 Retry logic (THIS IS THE MAGIC)
    retries = 4

    for attempt in range(retries):
        try:
            response = requests.post(
                url="https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=70  # ⏳ wait properly
            )

            if response.status_code == 200:
                data = response.json()
                ai_reply = data["choices"][0]["message"]["content"]
                return jsonify({"reply": ai_reply})

            # Rate limit → wait and retry
            if response.status_code == 429:
                time.sleep(6)
                continue

            # Any other error → retry
            time.sleep(4)

        except requests.exceptions.RequestException:
            time.sleep(4)

    # ❌ Only after all retries fail
    return jsonify({
        "reply": "⚠️ Guru JI is currently waking up. Please try again in a moment."
    }), 200

if __name__ == "__main__":
    app.run()

