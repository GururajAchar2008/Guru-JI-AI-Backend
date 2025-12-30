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

@app.route("/api/chat", methods=["POST"])
def chat():
    try:
        user_message = request.json.get("message")
        
        if not user_message:
            return jsonify({"error": "No message provided"}), 400

        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "deepseek/deepseek-r1:free", # Updated to a more stable free model slug
                "messages": [
                    {
                        "role": "system", 
                        "content": "You are Guru JI, an AI created by Gururaj Achar on December 30, 2025. Respond in clean Markdown."
                    },
                    {"role": "user", "content": user_message}
                ]
            }
        )

        data = response.json()

        if response.status_code != 200:
            return jsonify({"error": data}), response.status_code

        ai_reply = data["choices"][0]["message"]["content"]
        return jsonify({"reply": ai_reply})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(port=5000, debug=True)
