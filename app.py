from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import os
import time
from dotenv import load_dotenv
from PyPDF2 import PdfReader

load_dotenv()

app = Flask(__name__)
CORS(app)
CURRENT_FILE_CONTEXT = ""
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# In-memory conversation store (simple & effective)
conversation_history = []

@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "Guru JI backend"}), 200


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.json
    messages = data.get("messages")

    if not messages:
        return jsonify({"error": "No messages provided"}), 400

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
                    "You are Guru JI, a calm, wise AI guide created by Gururaj Achar. answer in the shortest way posible but informativly "
                    "Respond warmly, clearly, and in clean Markdown. respond like a teacher from karnataka"
                    "Understand context from previous messages. respond only in english language "
                )
            },
            *messages
        ]
    }

    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=120,
            stream=False
        )

        data = response.json()
        reply = data["choices"][0]["message"]["content"]
        return jsonify({ "reply": reply })

    except Exception:
        return jsonify({
            "reply": "⏳ Guru JI is waking up. Please wait a moment."
        }), 200


@app.route("/api/upload", methods=["POST"])
def upload_file():
    if "file" not in request.files:
        return jsonify({"reply": "No file received"}), 400

    file = request.files["file"]
    text = ""

    if file.filename.endswith(".pdf"):
        reader = PdfReader(file)
        for page in reader.pages:
            text += page.extract_text() or ""

    elif file.filename.endswith(".txt"):
        text = file.read().decode("utf-8")

    else:
        return jsonify({"reply": "Unsupported file type"}), 400

    if not text.strip():
        return jsonify({"reply": "No readable text found in file"}), 400

    return jsonify({
        "reply": "📄 File uploaded successfully",
        "content": text[:3000]  # limit for safety
    })
