from flask import Flask, render_template, request, jsonify, session
from dotenv import load_dotenv
from pathlib import Path
import os
import json
import time
from datetime import date, timedelta

import database
import memory_engine
import chatbot

BASE_DIR = Path(__file__).resolve().parent
# Use this app's local configuration even when a blank or stale key was
# inherited from PowerShell, VS Code, or another parent process.
load_dotenv(BASE_DIR / ".env", override=True)

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "recallai-local-development-key")

database.initialize_database()


def login_required():
    user_id = session.get("user_id")
    return database.get_user(user_id) if user_id else None


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/challenge")
def challenge_page():
    if not login_required():
        return render_template("index.html")
    return render_template("challenge.html")


@app.route("/dashboard")
def dashboard_page():
    if not login_required():
        return render_template("index.html")
    return render_template("dashboard.html")


@app.route("/journal")
def journal_page():
    if not login_required():
        return render_template("index.html")
    return render_template("index.html")


@app.route("/api/user", methods=["GET", "POST"])
def user_api():
    if request.method == "GET":
        user = login_required()
        return jsonify({"success": bool(user), "user": user})

    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()

    if not username or len(username) > 40:
        return jsonify({
            "success": False,
            "message": "Enter a username of 1–40 characters."
        }), 400

    user = database.create_user(username)
    session["user_id"] = user["id"]
    session.pop("active_challenge_id", None)
    session.pop("challenge_start_time", None)

    return jsonify({"success": True, "user": user})


@app.route("/api/session/start", methods=["POST"])
def session_start():
    user = login_required()
    if not user:
        return jsonify({"success": False, "message": "Enter your username first."}), 401

    session_id = database.create_session(user["id"])
    session["session_id"] = session_id
    return jsonify({"success": True, "session_id": session_id})


@app.route("/api/chat", methods=["POST"])
def chat_api():
    user = login_required()
    if not user:
        return jsonify({"success": False, "message": "Enter your username first."}), 401

    data = request.get_json(silent=True) or {}
    message = str(data.get("message", "")).strip()

    if not message or len(message) > 4000:
        return jsonify({"success": False, "message": "Enter a message of 1–4000 characters."}), 400

    if chatbot.is_journal_capture(message):
        entry_date = chatbot.entry_date_for_message(message)
        content = chatbot.clean_entry_content(message)
        if not entry_date or not content or len(content) > 4000:
            return jsonify({"success": False, "message": "Please include a journal entry and a valid date."}), 400
        entry = database.create_journal_entry(user["id"], entry_date, content)
        reply = f"Saved to your journal for {entry_date}: {content}"
        database.save_chat_turn(user["id"], message, reply)
        return jsonify({"success": True, "response": {
            "intent": "journal_saved",
            "message": reply,
            "action": None,
            "entry": entry
        }})

    if chatbot.journal_action(message):
        entries = database.get_journal_entries(user["id"], limit=5000)
        reply = chatbot.journal_response(message, entries)
        database.save_chat_turn(user["id"], message, reply)
        return jsonify({"success": True, "response": {
            "intent": "journal_recall",
            "message": reply,
            "action": None
        }})

    skills = database.get_all_skills(user["id"])
    attempts = database.get_user_attempts(user["id"])

    intent = chatbot.detect_intent(message)
    statistics = {
        "attempts": len(attempts),
        "overall_score": memory_engine.calculate_overall_score(skills)
    }

    # Keep app navigation and performance actions fully local and deterministic.
    if intent in ("practice", "progress"):
        result = chatbot.get_response(message, user=user, statistics=statistics)
    elif chatbot.ai_enabled():
        history = database.get_chat_history(user["id"], limit=12)
        try:
            result = chatbot.get_ai_response(message, history=history)
        except chatbot.AIUnavailableError as error:
            return jsonify({"success": False, "message": str(error)}), 503
    elif intent != "unknown":
        # Existing basic replies continue to work when no API key is configured.
        result = chatbot.get_response(message, user=user, statistics=statistics)
    else:
        return jsonify({
            "success": False,
            "message": "To turn on general answers at no charge, create a Gemini API key in Google AI Studio and add GEMINI_API_KEY=your-key to the project's .env file, then restart RecallAI. Use the free tier only; don't set up billing. Free-tier prompts may be used by Google to improve its products, so don't send sensitive information."
        }), 503

    database.save_chat_turn(
        user["id"], message, result["message"], citations=result.get("citations", [])
    )

    return jsonify({"success": True, "response": result})


@app.route("/api/chat/history", methods=["GET", "DELETE"])
def chat_history_api():
    user = login_required()
    if not user:
        return jsonify({"success": False, "message": "Enter your username first."}), 401
    if request.method == "DELETE":
        database.clear_chat_history(user["id"])
        return jsonify({"success": True})
    return jsonify({
        "success": True,
        "ai_enabled": chatbot.ai_enabled(),
        "messages": database.get_chat_history(user["id"])
    })


@app.route("/api/journal", methods=["GET", "POST"])
def journal_api():
    user = login_required()
    if not user:
        return jsonify({"success": False, "message": "Enter your username first."}), 401

    if request.method == "GET":
        selected_date = request.args.get("date", "").strip()
        if selected_date:
            try:
                selected_date = date.fromisoformat(selected_date).isoformat()
            except ValueError:
                return jsonify({"success": False, "message": "Use a valid date in YYYY-MM-DD format."}), 400
            entries = database.get_journal_entries(
                user["id"], selected_date, selected_date, limit=500
            )
        else:
            try:
                days = max(1, min(3650, int(request.args.get("days", "30"))))
            except ValueError:
                return jsonify({"success": False, "message": "Days must be a number."}), 400
            entries = database.get_journal_entries(
                user["id"], (date.today() - timedelta(days=days - 1)).isoformat(),
                limit=500
            )
        return jsonify({"success": True, "entries": entries})

    data = request.get_json(silent=True) or {}
    content = str(data.get("content", "")).strip()
    raw_date = str(data.get("date", date.today().isoformat())).strip()
    try:
        entry_date = date.fromisoformat(raw_date).isoformat()
    except ValueError:
        return jsonify({"success": False, "message": "Use a valid date in YYYY-MM-DD format."}), 400
    if not content or len(content) > 4000:
        return jsonify({"success": False, "message": "Journal entries must be 1–4000 characters."}), 400
    entry = database.create_journal_entry(user["id"], entry_date, content)
    return jsonify({"success": True, "entry": entry})


@app.route("/api/journal/<int:entry_id>", methods=["PATCH", "DELETE"])
def journal_entry_api(entry_id):
    user = login_required()
    if not user:
        return jsonify({"success": False, "message": "Enter your username first."}), 401

    if request.method == "DELETE":
        if not database.delete_journal_entry(user["id"], entry_id):
            return jsonify({"success": False, "message": "Journal entry not found."}), 404
        return jsonify({"success": True})

    data = request.get_json(silent=True) or {}
    content = str(data.get("content", "")).strip()
    raw_date = str(data.get("date", "")).strip()
    try:
        entry_date = date.fromisoformat(raw_date).isoformat()
    except ValueError:
        return jsonify({"success": False, "message": "Use a valid date in YYYY-MM-DD format."}), 400
    if not content or len(content) > 4000:
        return jsonify({"success": False, "message": "Journal entries must be 1–4000 characters."}), 400
    entry = database.update_journal_entry(user["id"], entry_id, entry_date, content)
    if not entry:
        return jsonify({"success": False, "message": "Journal entry not found."}), 404
    return jsonify({"success": True, "entry": entry})



@app.route("/api/challenge/start", methods=["POST"])
def challenge_start():
    user = login_required()
    if not user:
        return jsonify({
            "success": False,
            "message": "Enter your username first."
        }), 401

    session_id = session.get("session_id")
    if not session_id:
        session_id = database.create_session(user["id"])
        session["session_id"] = session_id

    skills = database.get_all_skills(user["id"])
    challenge_type = memory_engine.choose_challenge_type(skills)

    existing_skill = next(
        (s for s in skills if s["challenge_type"] == challenge_type),
        None
    )

    if existing_skill:
        difficulty = existing_skill["level"]
    else:
        difficulty = 1

    challenge = memory_engine.generate_challenge(
        challenge_type, difficulty
    )
    client_challenge = dict(challenge)

    if challenge_type == "story":
        client_challenge["questions"] = [
            {"question": q["question"]}
            for q in challenge["questions"]
        ]

    challenge_id = database.create_challenge(
        session_id,
        challenge_type,
        difficulty,
        json.dumps(challenge)
    )

    session["active_challenge_id"] = challenge_id
    session["challenge_start_time"] = time.time()

    return jsonify({
        "success": True,
        "challenge_id": challenge_id,
        "challenge": client_challenge
    })


@app.route("/api/challenge/submit", methods=["POST"])
def challenge_submit():
    user = login_required()
    challenge_id = session.get("active_challenge_id")

    if not user or not challenge_id:
        return jsonify({
            "success": False,
            "message": "No active challenge. Start a new one."
        }), 400

    row = database.get_challenge(challenge_id, user["id"])
    if not row:
        return jsonify({"success": False, "message": "Challenge not found."}), 404

    if row["submitted_at"]:
        return jsonify({"success": False, "message": "Already submitted."}), 400

    data = request.get_json(silent=True) or {}
    answer = data.get("answer", "")
    challenge = json.loads(row["challenge_data"])
    kind = row["challenge_type"]

    if kind == "word":
        result = memory_engine.evaluate_word_answer(
            challenge["items"], answer if isinstance(answer, str) else ""
        )
    elif kind == "number":
        result = memory_engine.evaluate_number_answer(
            challenge["items"], answer if isinstance(answer, str) else ""
        )
    elif kind == "story":
        result = memory_engine.evaluate_story_answer(
            challenge["questions"], answer if isinstance(answer, list) else []
        )
    else:
        return jsonify({"success": False, "message": "Unknown challenge type."}), 400

    response_time = round(
        max(0, time.time() - session.get("challenge_start_time", time.time())),
        2
    )

    old_skill = database.get_skill(user["id"], kind)
    old_score = old_skill["skill_score"] if old_skill else 0
    old_attempts = old_skill["attempts"] if old_skill else 0

    new_score = memory_engine.calculate_new_skill(
    old_score,
    result["score"],
    old_attempts
    )
    new_level = memory_engine.difficulty_from_skill(new_score)

    database.save_attempt(
        challenge_id, user["id"], result["score"],
        result["correct_count"], result["total_count"],
        response_time, json.dumps(result)
    )
    database.save_skill(
        user["id"], kind, new_score, new_level, old_attempts + 1
    )

    session.pop("active_challenge_id", None)
    session.pop("challenge_start_time", None)

    return jsonify({
        "success": True,
        "result": result,
        "skill": {
            "challenge_type": kind,
            "skill_score": new_score,
            "level": new_level
        }
    })


@app.route("/api/dashboard")
def dashboard_api():
    user = login_required()
    if not user:
        return jsonify({"success": False, "message": "Enter your username first."}), 401

    skills = database.get_all_skills(user["id"])
    attempts = database.get_user_attempts(user["id"])

    return jsonify({
        "success": True,
        "overall_score": memory_engine.calculate_overall_score(skills),
        "attempts": len(attempts),
        "skills": skills,
        "recent_attempts": attempts[:10]
    })


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
