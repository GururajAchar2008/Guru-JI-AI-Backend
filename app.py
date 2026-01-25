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
# Store file context per session
FILE_CONTEXTS = {}



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
    session_id = data.get("session_id")

    if not messages or not session_id:
        return jsonify({"error": "Missing data"}), 400

    file_context = FILE_CONTEXTS.get(session_id, "")

    system_prompt = (
        "You are GuruJI AI, its just a name for you but you are a calm, wise AI teacher created by Gururaj Achar. "
        "Respond warmly, clearly, and in clean Markdown. "
        "Answer briefly but short and informatively. "
        "Respond like a teacher from Karnataka. "
        "Respond only in English."
    )

    if file_context:
        system_prompt += (
            "\n\nUse the following document as the PRIMARY source:\n"
            f"{file_context[:12000]}"
        )

    payload = {
        "model": "deepseek/deepseek-r1-0528:free",
        "messages": [
            { "role": "system", "content": system_prompt },
            *messages
        ]
    }

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=180
        )

        data = response.json()
        reply = data["choices"][0]["message"]["content"]
        return jsonify({ "reply": reply })

    except Exception:
        return jsonify({
            "reply": "⏳ Guru JI is waking up. Please wait a moment."
        })



@app.route("/api/upload", methods=["POST"])
def upload_file():
    session_id = request.form.get("session_id")

    if not session_id:
        return jsonify({"reply": "Session ID missing"}), 400

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

    FILE_CONTEXTS[session_id] = text.strip()

    return jsonify({
        "reply": "📄 File uploaded successfully. You can now ask questions about it."
    })


