from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

@app.route("/api/chat", methods=["POST"])
def chat():
    try:
        user_message = request.json.get("message")

        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://gururajachar2008.github.io/Guru-JI-AI/",
                "X-Title": "Guru AI"
            },
            json={
                "model": "deepseek/deepseek-r1-0528:free",
                "messages": [
                    {"role": "system", "content": "Respond in clean markdown and your name is Guru JI and your was created by Gururaj achar and you was created in december 30 in year 2025."},
                    {"role": "user", "content": user_message}
                ]
            }
        )

        data = response.json()

        if response.status_code != 200:
            return jsonify({"error": data}), 500

        return jsonify({
            "reply": data["choices"][0]["message"]["content"]
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run()
