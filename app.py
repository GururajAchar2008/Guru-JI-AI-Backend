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
                    "You are Guru JI, a calm, wise AI guide created by Gururaj Achar.If a document is provided, use it as the PRIMARY source. answer in the shortest way posible but informativly "
                    "Respond warmly, clearly, and in clean Markdown. respond like a teacher from karnataka,Understand context from previous messages. respond only in english language "
                    f"Document content:\n{CURRENT_FILE_CONTEXT[:12000]}"
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
            timeout=180,
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
    global CURRENT_FILE_CONTEXT

    if "file" not in request.files:
        return jsonify({"reply": "No file received"}), 400

    file = request.files["file"]
    text = ""

    if file.filename.endswith(".pdf"):
        reader = PdfReader(file)
        for page in reader.pages:
            extracted = page.extract_text()
            if extracted:
                text += extracted + "\n"

    elif file.filename.endswith(".txt"):
        text = file.read().decode("utf-8")

    else:
        return jsonify({"reply": "Unsupported file type"}), 400

    CURRENT_FILE_CONTEXT = text.strip()

    return jsonify({"reply": "📄 File uploaded successfully. You can now ask questions about it."})

