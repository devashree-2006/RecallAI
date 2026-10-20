import re
import json
import os
import urllib.error
import urllib.request
from datetime import date, timedelta

INTENTS = {
    "greeting": ["hi", "hello", "hey", "good morning", "good evening"],
    "practice": ["start", "practice", "challenge me", "memory test", "test me", "quiz me", "test my memory"],
    "progress": ["progress", "performance", "statistics", "my score", "my results"],
    "types": ["challenge types", "what tests", "what challenges", "memory exercises"],
    "explain": ["how does it work", "what is recallai", "explain recallai"],
    "help": ["help", "commands", "what can i do"],
    "capabilities": ["what can you do", "what can recallai do", "features", "how can you help"],
    "tips": ["memory tip", "memory tips", "improve my memory", "remember better", "study tips"]
}

DATE_PATTERN = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
STOP_WORDS = set("about after again also and are because before been being between could did does doing done during each from have having here how into just more most much not only other our out over same she should some than that the their them then there these they this those through today tomorrow under until very was were what when where which while who why will with would your yours yesterday activity activities went had have has worked work workin working studied study studying attended visited meet met called call cooked ate eat bought buy".split())

AI_INSTRUCTIONS = """You are RecallAI, a friendly, clear assistant inside a personal memory and journal app. Answer the user's actual question directly and helpfully across general topics. Never invent personal details about the user: personal activity can only be recalled from explicit saved journal entries handled by the app. If you do not know something, say so. Do not claim to have searched the web or cite sources you were not given. For facts that may have changed, mention that the user should verify them with a current source. Keep answers readable and appropriately concise. If the user asks to start a memory challenge or view progress, the app handles that with its built-in actions."""


class AIUnavailableError(RuntimeError):
    """Raised when general answers cannot be generated or the service fails."""


def ai_provider():
    """Gemini is the no-billing default; OpenAI is opt-in only."""
    return os.getenv("AI_PROVIDER", "gemini").strip().lower()


def _usable_key(value, placeholders):
    key = (value or "").strip()
    return bool(key and key.lower() not in placeholders)


def ai_enabled():
    provider = ai_provider()
    if provider == "openai":
        return _usable_key(os.getenv("OPENAI_API_KEY"), {
            "your-openai-api-key", "replace-me", "changeme", "your_api_key"
        })
    if provider == "gemini":
        return _usable_key(os.getenv("GEMINI_API_KEY"), {
            "your-gemini-api-key", "replace-me", "changeme", "your_api_key"
        })
    return False


def _response_text_and_citations(payload):
    parts = []
    citations = []
    for item in payload.get("output", []):
        if item.get("type") != "message" or item.get("role") != "assistant":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                if content.get("text"):
                    parts.append(content["text"])
                for annotation in content.get("annotations", []):
                    if annotation.get("type") != "url_citation":
                        continue
                    citation = annotation.get("url_citation", annotation)
                    url = citation.get("url")
                    if url and url.startswith("https://"):
                        citations.append({"title": citation.get("title") or url, "url": url})
    unique = []
    seen = set()
    for citation in citations:
        if citation["url"] not in seen:
            unique.append(citation)
            seen.add(citation["url"])
    return "\n".join(parts).strip(), unique


def _get_openai_response(message, history=None):
    """Optional paid OpenAI provider for users who explicitly select it."""
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise AIUnavailableError("RecallAI can save and recall your journal, run memory practice, and share built-in tips without AI setup. To answer broad general questions, create a local .env file from .env.example and add your OpenAI API key there, then restart RecallAI. Never paste the key into chat.")

    conversation = []
    skip_journal_reply = False
    for item in (history or [])[-24:]:
        role = item.get("role")
        content = str(item.get("message", "")).strip()
        if not content or role not in ("user", "assistant"):
            continue
        if role == "user":
            skip_journal_reply = bool(journal_action(content) or is_journal_capture(content))
            if skip_journal_reply:
                continue
        elif role == "assistant" and skip_journal_reply:
            skip_journal_reply = False
            continue
        conversation.append({"role": role, "content": content})
    conversation.append({"role": "user", "content": message})
    body = json.dumps({
        "model": os.getenv("OPENAI_MODEL", "gpt-5.2"),
        "instructions": AI_INSTRUCTIONS,
        "input": conversation,
        "tools": [{"type": "web_search"}],
        "store": False,
        "max_output_tokens": 800
    }).encode("utf-8")
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses", data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        if error.code == 401:
            detail = "The OpenAI API key was rejected. Check OPENAI_API_KEY in .env."
        elif error.code == 429:
            detail = "OpenAI is rate limited or the API account has no available quota. Try again later or check its billing and limits."
        else:
            detail = f"OpenAI could not answer right now (HTTP {error.code}). Please try again."
        raise AIUnavailableError(detail) from None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        raise AIUnavailableError("I couldn't reach the answer service just now. Check your connection and try again.") from None

    answer, citations = _response_text_and_citations(payload)
    if not answer:
        raise AIUnavailableError("I didn't receive an answer this time. Please try asking in a different way.")
    return {"intent": "general", "message": answer, "action": None, "citations": citations}


def _retry_gemini_fallback(message, history, primary_model, allow_fallback, reason):
    if not allow_fallback:
        return None
    fallback_model = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.6-flash").strip()
    if not fallback_model or fallback_model == primary_model:
        return None
    try:
        result = _get_gemini_response(
            message, history, model_override=fallback_model, allow_fallback=False
        )
    except AIUnavailableError as fallback_error:
        raise AIUnavailableError(
            f"Gemini's primary model {primary_model} had a {reason}, and backup model "
            f"{fallback_model} also failed. {fallback_error}"
        ) from None
    result["message"] = (
        f"{primary_model} had a {reason}, so I answered with {fallback_model}.\n\n"
        f"{result['message']}"
    )
    return result


def _get_gemini_response(message, history=None, model_override=None, allow_fallback=True):
    """Answer general questions through Gemini's API free tier."""
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise AIUnavailableError("Add a Gemini API key from Google AI Studio to GEMINI_API_KEY in your local .env file, then restart RecallAI. The free tier has usage limits. Do not paste your key into chat.")

    contents = []
    skip_journal_reply = False
    for item in (history or [])[-24:]:
        role = item.get("role")
        content = str(item.get("message", "")).strip()
        if not content or role not in ("user", "assistant"):
            continue
        if role == "user":
            skip_journal_reply = bool(journal_action(content) or is_journal_capture(content))
            if skip_journal_reply:
                continue
        elif role == "assistant" and skip_journal_reply:
            skip_journal_reply = False
            continue
        contents.append({
            "role": "user" if role == "user" else "model",
            "parts": [{"text": content}]
        })
    contents.append({"role": "user", "parts": [{"text": message}]})

    body = json.dumps({
        "system_instruction": {"parts": [{"text": AI_INSTRUCTIONS}]},
        "contents": contents,
        "generation_config": {"max_output_tokens": 800}
    }).encode("utf-8")
    model = (model_override or os.getenv("GEMINI_MODEL", "gemini-3.8-flash")).strip()
    request = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        data=body,
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        try:
            error_payload = json.loads(error.read().decode("utf-8"))
            api_error = error_payload.get("error", {})
            api_message = str(api_error.get("message") or "")
        except (AttributeError, UnicodeDecodeError, json.JSONDecodeError):
            api_error = {}
            api_message = ""
        if error.code == 503:
            result = _retry_gemini_fallback(
                message, history, model, allow_fallback, "temporary overload"
            )
            if result:
                return result
        if error.code in (401, 403):
            detail = "Google rejected the Gemini key or its API access. Check GEMINI_API_KEY and make sure the key is enabled for the Gemini API."
        elif error.code == 429:
            detail = "Gemini's free-tier request limit was reached. Wait for the limit to reset, then try again. No payment is needed to keep using the free tier."
        elif error.code == 404:
            detail = "The configured Gemini model was not found or is unavailable to this project. Check GEMINI_MODEL in .env."
        elif error.code == 503:
            detail = f"Gemini is temporarily busy (HTTP 503). {api_message[:240]} Please try again later."
        else:
            detail = f"Gemini could not answer right now (HTTP {error.code}). {api_message[:240]} Please try again."
        raise AIUnavailableError(detail) from None
    except urllib.error.URLError as error:
        result = _retry_gemini_fallback(
            message, history, model, allow_fallback, "connection failure"
        )
        if result:
            return result
        reason = str(error.reason).strip()
        detail = f"I couldn't reach Gemini just now. Connection detail: {reason[:180]}" if reason else "I couldn't reach Gemini just now. Check your connection and try again."
        raise AIUnavailableError(detail) from None
    except TimeoutError:
        result = _retry_gemini_fallback(
            message, history, model, allow_fallback, "request timeout"
        )
        if result:
            return result
        raise AIUnavailableError("Gemini took too long to respond. Check your connection and try again.") from None
    except json.JSONDecodeError:
        raise AIUnavailableError("Gemini returned a response RecallAI couldn't read. Please try again.") from None

    candidates = payload.get("candidates", [])
    answer_parts = []
    if candidates:
        for part in candidates[0].get("content", {}).get("parts", []):
            if part.get("text"):
                answer_parts.append(part["text"])
    answer = "\n".join(answer_parts).strip()
    if not answer:
        raise AIUnavailableError("Gemini did not return a text answer. Try rephrasing the question.")
    return {"intent": "general", "message": answer, "action": None, "citations": []}


def get_ai_response(message, history=None):
    """Answer broad questions using the configured provider (Gemini by default)."""
    provider = ai_provider()
    if provider == "gemini":
        return _get_gemini_response(message, history)
    if provider == "openai":
        return _get_openai_response(message, history)
    raise AIUnavailableError("AI_PROVIDER must be set to gemini or openai in .env.")


def detect_intent(message):
    message = " ".join(str(message).lower().strip().split())
    if re.fullmatch(r"(?:hi|hello|hey|good morning|good evening)[!. ]*", message):
        return "greeting"
    # Only launch a challenge for a clear request. Matching the bare word
    # "quiz" used to hijack questions that merely discussed quizzes.
    practice_requests = (
        r"\bquiz me\b", r"\bquick quiz\b", r"\bstart (?:a )?(?:quiz|challenge|practice)\b",
        r"\bchallenge me\b", r"\bmemory test\b", r"\btest me\b",
        r"\btest my memory\b", r"\blet's practice\b", r"\blets practice\b"
    )
    if any(re.search(pattern, message) for pattern in practice_requests):
        return "practice"
    if any(re.search(rf"\b{re.escape(keyword)}\b", message) for keyword in INTENTS["progress"]):
        return "progress"
    for intent in ("types", "explain", "help", "capabilities", "tips"):
        if any(keyword in message for keyword in INTENTS[intent]):
            return intent
    return "unknown"


def journal_action(message):
    """Return an explicit journal action, or None for ordinary chat."""
    text = " ".join(str(message).lower().strip().split())
    if any(term in text for term in (
        "summarize my", "summarise my", "past few days", "last few days",
        "past week", "last week", "recent days", "what have i been up to",
        "recap my days", "journal summary", "summarize my journal"
    )):
        return "summary"
    if DATE_PATTERN.search(text) or re.search(r"\b(today|yesterday|\d+ days? ago)\b", text):
        if re.search(r"\b(what|when|where|did i|have i|tell me|recall|remember|show|summari[sz]e|recap)\b", text):
            return "recall"
    if any(term in text for term in (
        "what did i do", "what was i doing", "what happened", "what have i done",
        "my journal", "show my journal", "journal entries", "my timeline",
        "recall my day", "recap yesterday", "recap today"
    )):
        return "recall"
    return None


def is_journal_capture(message):
    text = " ".join(str(message).lower().strip().split())
    if journal_action(text):
        return False
    if any(term in text for term in ("journal:", "log this:", "remember that i ", "remember that we ")):
        return True
    has_date = bool(re.search(r"\b(today|yesterday|\d{4}-\d{2}-\d{2})\b", text))
    first_person_activity = bool(re.search(
        r"\b(i|we)\s+(?:did|went|was|were|had|have|met|visited|worked|studied|"
        r"attended|played|read|wrote|made|built|bought|ate|cooked|called|finished|"
        r"started|spent|took|saw|learned|practiced|travelled|traveled|exercised|"
        r"watched|joined|helped|completed|enjoyed|felt|talked|walked|ran|slept)\b", text
    ))
    present_day_statement = bool(re.match(r"^(today|yesterday)\s*[:,]?\s*(i|we)\b", text))
    return (has_date and (first_person_activity or present_day_statement)) or present_day_statement


def entry_date_for_message(message, today=None):
    today = today or date.today()
    text = str(message).lower()
    match = DATE_PATTERN.search(text)
    if match:
        try:
            return date.fromisoformat(match.group(1)).isoformat()
        except ValueError:
            return None
    if re.search(r"\byesterday\b", text):
        return (today - timedelta(days=1)).isoformat()
    if re.search(r"\btoday\b", text):
        return today.isoformat()
    ago = re.search(r"\b(\d+) days? ago\b", text)
    if ago:
        amount = int(ago.group(1))
        if amount > 3650:
            return None
        return (today - timedelta(days=amount)).isoformat()
    return today.isoformat()


def clean_entry_content(message):
    text = str(message).strip()
    text = re.sub(r"^(?:journal|log this)\s*:\s*", "", text, flags=re.I)
    text = re.sub(r"^(today|yesterday)\s*[:,]\s*", "", text, flags=re.I)
    text = re.sub(r"\b(?:today|yesterday)\b[.!?]*\s*$", "", text, flags=re.I)
    return text.strip()


def _recurring_details(entries):
    dates_by_word = {}
    for entry in entries:
        words = set(re.findall(r"[a-zA-Z]{4,}", entry["content"].lower())) - STOP_WORDS
        for word in words:
            dates_by_word.setdefault(word, set()).add(entry["entry_date"])
    repeated = sorted(
        ((len(dates), word) for word, dates in dates_by_word.items() if len(dates) >= 2),
        key=lambda pair: (-pair[0], pair[1])
    )
    return [word for _, word in repeated[:4]]


def journal_response(message, entries, today=None):
    today = today or date.today()
    action = journal_action(message) or "recall"
    text = str(message).lower()
    if action == "summary" or any(term in text for term in (
        "few days", "past week", "last week", "recent days", "past days"
    )):
        days = 7 if "week" in text else 4
        start = (today - timedelta(days=days - 1)).isoformat()
        selected = [e for e in entries if start <= e["entry_date"] <= today.isoformat()]
        label = f"your past {days} days"
    else:
        target = entry_date_for_message(message, today)
        if target is None:
            return "I couldn't read that date. Please use YYYY-MM-DD, today, or yesterday."
        selected = [e for e in entries if e["entry_date"] == target]
        label = "today" if target == today.isoformat() else "yesterday" if target == (today - timedelta(days=1)).isoformat() else target

    if not selected:
        return f"I don't have any saved journal entries for {label}. I only know what you've shared and saved here."

    grouped = {}
    for entry in sorted(selected, key=lambda e: (e["entry_date"], e["id"])):
        grouped.setdefault(entry["entry_date"], []).append(entry["content"])
    lines = [f"From your saved journal, here's {label}:"]
    for entry_day, contents in grouped.items():
        lines.append(f"{entry_day}:")
        lines.extend(f"• {content}" for content in contents)
    recurring = _recurring_details(selected)
    if recurring:
        lines.append("\nRecurring details in these entries: " + ", ".join(recurring) + ".")
    return "\n".join(lines)


def get_response(message, user=None, statistics=None):
    intent = detect_intent(message)
    username = user.get("username", "there") if user else "there"
    statistics = statistics or {}
    responses = {
        "greeting": f"Hi {username}! Welcome to RecallAI. Ready to exercise your memory? You can also tell me what you did today and I'll save it to your journal.",
        "practice": "Let's begin! I'll give you a memory challenge and evaluate your answer.",
        "types": "RecallAI offers three challenge types:\n1. Word Recall\n2. Number Recall\n3. Story Recall\nDifficulty adapts based on your performance.",
        "explain": "RecallAI presents a challenge, evaluates your response, updates your performance score, and adjusts future difficulty. Journal entries are saved separately so I can answer questions from what you've shared.",
        "help": "Try: 'Quiz me', 'Give me a memory tip', 'What did I do yesterday?', or 'Summarize my past few days.' You can also share what you did today, check your progress, or open your journal.",
        "capabilities": "I can run adaptive memory challenges, track your practice progress, save daily journal entries, recall saved days, and summarize recurring details from your journal. Ask for a memory tip, or try 'Quiz me'.",
        "tips": "Try active recall: close your notes and explain the idea from memory. Review it again after a short gap, then revisit it tomorrow. For lists, group related items or connect them to a vivid image. Want to practice with a quick challenge?"
    }
    if intent == "progress":
        attempts = statistics.get("attempts", 0)
        score = statistics.get("overall_score", 0)
        return {"intent": intent, "message": f"You have completed {attempts} challenge(s). Your current average skill score is {score}%" if attempts else "You haven't completed any challenges yet. Start practicing to build your progress history.", "action": "progress"}
    return {"intent": intent, "message": responses.get(intent, "I can run memory challenges, share memory tips, track your scores, and recall saved journal entries. Ask 'What can you do?' to see the options."), "action": "practice" if intent == "practice" else None}
