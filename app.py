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

load_dotenv()

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

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
            timeout=280
        )

        data = response.json()
        if "choices" in data:
            replay = data['choices'][0]["message"]["content"]
        if "output" in data:
            reply = data["output"][0]["message"]["content"]
        if "error" in data:
            reply = data["error"].get("message", "Unknown AI error")
        return jsonify({ "reply": reply })

    except Exception as e:
        print(f"Error in chat: {e}")
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
    emit('connected', {'message': 'Connected to GuruJI'})


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
    
    if room_id not in CLASSROOMS:
        return
    
    classroom = CLASSROOMS[room_id]
    
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
        f"You are GuruJI, an AI teacher conducting a live classroom session.\n"
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
        "model": "deepseek/deepseek-r1-0528:free",
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
            timeout=280
        )
        
        data = response.json()
        reply = data["choices"][0]["message"]["content"]
        
        # Broadcast response to entire classroom
        socketio.emit('guruji_response', {
            'response': reply,
            'timestamp': datetime.now().isoformat()
        }, room=room_id)
        
        print(f"GuruJI responded in classroom {room_id}")
        
    except Exception as e:
        print(f"Error generating response: {e}")
        socketio.emit('guruji_response', {
            'response': "⏳ I'm having trouble connecting right now. Please try asking again.",
            'timestamp': datetime.now().isoformat()
        }, room=room_id)


if __name__ == "__main__":
    # Use socketio.run instead of app.run for WebSocket support
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)
