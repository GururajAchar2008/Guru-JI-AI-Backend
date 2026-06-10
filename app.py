import eventlet
eventlet.monkey_patch()

from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_socketio import SocketIO, emit, join_room, leave_room
import requests
import os
import time
from dotenv import load_dotenv
from PyPDF2 import PdfReader
import uuid
from datetime import datetime
from rag_service import needs_web_search, web_search_context, build_rag_system_prompt


load_dotenv()

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")


# Store file context per session
FILE_CONTEXTS = {}

# Store active classrooms
CLASSROOMS = {}
# Structure: {
#   room_id: {
#     'topic': str,
#     'level': str,
#     'teacher_id': str,
#     'students': [{'id': str, 'name': str}],
#     'question_queue': [],
#     'last_response_time': timestamp,
#     'context': str
#   }
# }

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL = "openrouter/free"
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
OPENROUTER_MODEL_CACHE = {"value": None, "fetched_at": 0}
OPENROUTER_CHAT_TIMEOUT_SECONDS = 45


def _is_free_model(model):
    if not isinstance(model, dict):
        return False

    model_id = str(model.get("id", "")).strip()
    name = str(model.get("name", "")).strip()
    slug = f"{model_id} {name}".lower()

    pricing = model.get("pricing") or {}
    numeric_prices = []
    for key in ("prompt", "completion", "request"):
        value = pricing.get(key)
        try:
            numeric_prices.append(float(value))
        except (TypeError, ValueError):
            continue

    is_free_pricing = bool(numeric_prices) and all(price == 0.0 for price in numeric_prices)
    return bool(model_id) and ("/free" in slug or "free" in slug or is_free_pricing)


def fetch_free_openrouter_models():
    now = time.time()
    cached_models = OPENROUTER_MODEL_CACHE.get("value")
    fetched_at = OPENROUTER_MODEL_CACHE.get("fetched_at", 0)
    if cached_models and now - fetched_at < 900:
        return cached_models

    headers = {"Content-Type": "application/json"}
    if OPENROUTER_API_KEY:
        headers["Authorization"] = f"Bearer {OPENROUTER_API_KEY}"

    response = requests.get(OPENROUTER_MODELS_URL, headers=headers, timeout=20)
    response.raise_for_status()
    payload = response.json()
    models = payload.get("data", []) if isinstance(payload, dict) else []

    free_models = []
    for model in models:
        if not _is_free_model(model):
            continue

        free_models.append(
            {
                "id": model.get("id", ""),
                "name": model.get("name", model.get("id", "")),
                "provider": model.get("provider", ""),
                "context_length": model.get("context_length", 0),
            }
        )

    free_models.sort(
        key=lambda item: (item.get("name", "").lower(), item.get("id", "").lower())
    )
    OPENROUTER_MODEL_CACHE["value"] = free_models
    OPENROUTER_MODEL_CACHE["fetched_at"] = now
    return free_models


@app.route("/api/models", methods=["GET"])
def list_models():
    try:
        models = fetch_free_openrouter_models()
        return jsonify({
            "models": models,
            "default": OPENROUTER_MODEL,
        })
    except Exception as error:
        print(f"Error loading model list: {error}")
        return jsonify({
            "models": [{"id": OPENROUTER_MODEL, "name": "Auto (openrouter/free)"}],
            "default": OPENROUTER_MODEL,
        })


def extract_response_model(data, response=None):
    """
    OpenRouter always returns the actual model used in data["model"].
    When using openrouter/free, it replaces it with the real routed model name.
    """
    # 1. Best source: the response body's "model" field
    if isinstance(data, dict):
        model = data.get("model", "")
        if isinstance(model, str) and model.strip():
            return model.strip()

    # 2. Fallback: check response headers (x-openrouter-model is a real header)
    if response is not None:
        for header in ("x-openrouter-model", "x-model"):
            val = response.headers.get(header, "")
            if val:
                return val.strip()

    return ""

# In-memory conversation store (simple & effective)
conversation_history = []

@app.route("/", methods=["GET"])
def health():
    return jsonify({
        "status": "ok", 
        "service": "Guru JI backend",
        "active_classrooms": len(CLASSROOMS)
    }), 200


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.json
    messages = data.get("messages")
    session_id = data.get("session_id")
    requested_model = data.get("model") or OPENROUTER_MODEL

    if requested_model in ("auto", "", None):
        requested_model = OPENROUTER_MODEL

    if not messages or not session_id:
        return jsonify({"error": "Missing data"}), 400

    file_context = FILE_CONTEXTS.get(session_id, "")

    base_prompt = (
        "You are Velkor AI, a calm, wise AI teacher created by Gururaj Achar. "
        "Respond warmly, clearly, and in clean Markdown. "
        "Answer briefly but short and informatively. "
        "Respond only in English."
    )

    # --- RAG: Fetch live web context if query needs current info ---
    last_user_message = next(
        (m["content"] for m in reversed(messages) if m["role"] == "user"), ""
    )
    web_context = ""
    rag_used = False

    if needs_web_search(last_user_message):
        web_context = web_search_context(last_user_message)
        rag_used = bool(web_context)

    system_prompt = build_rag_system_prompt(base_prompt, web_context, file_context)

    payload = {
        "model": requested_model,
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
            timeout=(10, OPENROUTER_CHAT_TIMEOUT_SECONDS)
        )

        try:
            data = response.json()
        except ValueError:
            data = {
                "error": {
                    "message": response.text.strip() or "Invalid response from the AI service.",
                }
            }
        reply = "⚠️ Guru JI could not generate a response."
        
        if isinstance(data, dict):
            if "choices" in data and data["choices"]:
                reply = data["choices"][0]["message"]["content"]
            elif "output" in data and data["output"]:
                reply = data["output"][0]["content"]
            elif "error" in data:
                reply = data["error"].get("message", reply)
                
        response_model = extract_response_model(data, response)
        return jsonify({
            "reply": reply,
            "rag_used": rag_used,
            "model": response_model,
        })

    except requests.exceptions.Timeout:
        print("Error in chat: OpenRouter request timed out")
        return jsonify({
            "error": {
                "message": "VELKOR AI timed out while generating the answer. Please try again."
            }
        }), 504

    except Exception as e:
        print(f"Error in chat: {e}")
        return jsonify({
            "error": {
                "message": "VELKOR AI could not finish the request. Please try again."
            }
        }), 502


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
        
    elif file.filename.endswith(".html"):
        text = file.read().decode("utf-8")
        
    elif file.filename.endswith(".css"):
        text = file.read().decode("utf-8")

    elif file.filename.endswith(".js"):
        text = file.read().decode("utf-8")

    elif file.filename.endswith(".py"):
        text = file.read().decode("utf-8")

    elif file.filename.endswith(".jsx"):
        text = file.read().decode("utf-8")
        
    elif file.filename.endswith(".jpeg") or file.filename.endswith(".jpg") or file.filename.endswith(".png"):
        text = file.read().decode("utf-8")

    else:
        return jsonify({"reply": "Unsupported file type, For now i only accept PDF (.pdf) and TEXT (.txt) file formates for educational purposes only"}), 400

    FILE_CONTEXTS[session_id] = text.strip()

    return jsonify({
        "reply": "📄 File uploaded successfully. You can now ask questions about it."
    })


# ==================== CLASSROOM ENDPOINTS ====================

@app.route("/api/classroom/create", methods=["POST"])
def create_classroom():
    data = request.json
    topic = data.get("topic")
    level = data.get("level", "school")
    teacher_id = data.get("teacher_id")
    
    if not topic or not teacher_id:
        return jsonify({"error": "Missing data"}), 400
    
    room_id = str(uuid.uuid4())[:8].upper()
    
    CLASSROOMS[room_id] = {
        'topic': topic,
        'level': level,
        'teacher_id': teacher_id,
        'students': [],
        'question_queue': [],
        'last_response_time': None,
        'context': ''
    }
    
    return jsonify({
        "room_id": room_id,
        "topic": topic,
        "level": level
    })


# ==================== WEBSOCKET EVENTS ====================

@socketio.on('connect')
def handle_connect():
    print(f"Client connected: {request.sid}")
    emit('connected', {'message': 'Connected to Velkor AI'})


@socketio.on('disconnect')
def handle_disconnect():
    print(f"Client disconnected: {request.sid}")


@socketio.on('create_classroom')
def handle_create_classroom(data):
    room_id = data.get('room_id')
    join_room(room_id)
    print(f"Teacher created classroom: {room_id}")


@socketio.on('join_classroom')
def handle_join_classroom(data):
    room_id = data.get('room_id')
    student_name = data.get('student_name')
    student_id = data.get('student_id')
    
    if room_id not in CLASSROOMS:
        emit('join_error', {'message': 'Classroom not found'})
        return
    
    classroom = CLASSROOMS[room_id]
    
    # Add student to classroom
    student = {'id': student_id, 'name': student_name}
    if student not in classroom['students']:
        classroom['students'].append(student)
    
    join_room(room_id)
    
    # Notify all in room
    emit('student_joined', {
        'student_name': student_name,
        'students': [s['name'] for s in classroom['students']]
    }, room=room_id)
    
    # Send success to the joining student
    emit('join_success', {
        'topic': classroom['topic'],
        'level': classroom['level'],
        'students': [s['name'] for s in classroom['students']]
    })
    
    print(f"Student {student_name} joined classroom {room_id}")


@socketio.on('leave_classroom')
def handle_leave_classroom(data):
    room_id = data.get('room_id')
    student_name = data.get('student_name')
    
    if room_id in CLASSROOMS:
        classroom = CLASSROOMS[room_id]
        classroom['students'] = [s for s in classroom['students'] if s['name'] != student_name]
        
        leave_room(room_id)
        
        emit('student_left', {
            'student_name': student_name,
            'students': [s['name'] for s in classroom['students']]
        }, room=room_id)
        
        print(f"Student {student_name} left classroom {room_id}")


@socketio.on('student_question')
def handle_student_question(data):
    room_id = data.get('room_id')
    student_name = data.get('student_name')
    question = data.get('question')
    requested_model = data.get('model')
    
    if room_id not in CLASSROOMS:
        return
    
    classroom = CLASSROOMS[room_id]

    # If the teacher provided a preferred model, save it for this classroom
    if isinstance(requested_model, str) and student_name and student_name.lower() == 'teacher':
        classroom['selected_model'] = requested_model
    
    # Broadcast question to all students
    emit('student_question', {
        'student_name': student_name,
        'question': question
    }, room=room_id)
    
    # Add to question queue
    classroom['question_queue'].append({
        'student': student_name,
        'question': question,
        'timestamp': datetime.now()
    })
    
    print(f"Question from {student_name} in {room_id}: {question}")
    
    # Process questions after a short delay (batch processing)
    # In production, use Celery or similar for better handling
    socketio.start_background_task(process_questions, room_id)


def process_questions(room_id):
    """Process batched questions and generate AI response"""
    time.sleep(3)  # Wait to batch multiple questions
    
    if room_id not in CLASSROOMS:
        return
    
    classroom = CLASSROOMS[room_id]
    
    if not classroom['question_queue']:
        return
    
    # Prevent duplicate processing
    current_time = datetime.now()
    if classroom['last_response_time']:
        time_diff = (current_time - classroom['last_response_time']).seconds
        if time_diff < 5:  # Don't process if responded in last 5 seconds
            return
    
    # Get all pending questions
    questions = classroom['question_queue'].copy()
    classroom['question_queue'] = []
    classroom['last_response_time'] = current_time
    
    # Build context for AI
    topic = classroom['topic']
    level = classroom['level']
    
    # Format questions
    question_text = "\n".join([
        f"- {q['student']}: {q['question']}"
        for q in questions
    ])
    
    # Create teaching prompt
    system_prompt = (
        f"You are VELKOR AI, an AI teacher conducting a live classroom session.\n"
        f"Topic: {topic}\n"
        f"Level: {level}\n\n"
        f"Students have asked the following questions:\n{question_text}\n\n"
        f"Respond like a real teacher addressing the entire class:\n"
        f"- Address students by name when answering their questions\n"
        f"- Group similar questions together\n"
        f"- Explain clearly and engagingly\n"
        f"- Use examples and analogies\n"
        f"- Keep it conversational but educational and keep the answer as short as posible\n"
        f"- Format in clean Markdown\n"
        f"- Keep response focused (200-400 words)\n"
    )
    
    payload = {
        "model": classroom.get('selected_model', OPENROUTER_MODEL),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "Please address the students' questions."}
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
            timeout=90
        )
        
        data = response.json()
        reply = data["choices"][0]["message"]["content"]
        response_model = extract_response_model(data, response)
        
        # Broadcast response to entire classroom
        socketio.emit('guruji_response', {
            'response': reply,
            'model': response_model,
            'timestamp': datetime.now().isoformat()
        }, room=room_id)
        
        print(f"Velkor AI responded in classroom {room_id}")
        
    except Exception as e:
        print(f"Error generating response: {e}")
        socketio.emit('guruji_response', {
            'response': "⏳ I'm having trouble connecting right now. Please try asking again.",
            'model': "",
            'timestamp': datetime.now().isoformat()
        }, room=room_id)


if __name__ == "__main__":
    # Use socketio.run instead of app.run for WebSocket support
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)
