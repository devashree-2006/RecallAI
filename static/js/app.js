let currentChallenge = null;
let currentChallengeId = null;
let challengeTimer = null;

document.addEventListener("DOMContentLoaded", loadCurrentUser);

document.addEventListener("DOMContentLoaded", () => {
    const dateInput = document.getElementById("journalDate");
    if (dateInput) dateInput.value = localDateISO();
    if (window.location.pathname === "/journal") showJournal();
});

async function loadCurrentUser() {
    try {
        const response = await fetch("/api/user");
        const data = await response.json();

        if (data.success && data.user) {
            showLoggedInUser(data.user);
            await loadChatHistory();
        }
    } catch (error) {
        console.error("User loading error:", error);
    }
}

async function loadChatHistory() {
    const container = document.getElementById("chatMessages");
    if (!container) return;
    try {
        const response = await fetch("/api/chat/history");
        const data = await response.json();
        if (!response.ok || !data.success) return;
        const statusText = document.getElementById("chatStatusText");
        const statusDot = document.getElementById("chatStatusDot");
        if (statusText) statusText.textContent = data.ai_enabled
            ? "AI answers are ready · journal recalls use saved entries"
            : "Journal, quizzes & tips work · add an API key for broad answers";
        if (statusDot) statusDot.classList.toggle("status-dot-offline", !data.ai_enabled);
        document.getElementById("aiSetupNotice")?.classList.toggle("hidden", data.ai_enabled);
        container.replaceChildren();
        if (!data.messages.length) {
            addBotMessage("Hi! I'm RecallAI. Save a note about today, ask RecallAI any general question, or ask what your journal says about earlier days.");
            return;
        }
        data.messages.forEach(item => {
            if (item.role === "user") addUserMessage(item.message, item.created_at);
            else addBotMessage(item.message, item.created_at, item.citations || []);
        });
    } catch (error) {
        console.error("Chat history loading error:", error);
    }
}

async function clearChatHistory() {
    if (!window.confirm("Start a new chat? This clears the saved conversation but keeps your journal and progress.")) return;
    try {
        const response = await fetch("/api/chat/history", { method: "DELETE" });
        const data = await response.json();
        if (!response.ok || !data.success) throw new Error(data.message || "Could not clear the conversation.");
        const container = document.getElementById("chatMessages");
        if (container) container.replaceChildren();
        addBotMessage("Fresh start! I can run a quick memory quiz, share a memory tip, or help you recall your saved journal.");
    } catch (error) {
        alert(error.message);
    }
}

async function exportChatHistory() {
    try {
        const response = await fetch("/api/chat/history");
        const data = await response.json();
        if (!response.ok || !data.success) throw new Error(data.message || "Could not download the conversation.");
        if (!data.messages.length) {
            alert("There are no saved messages to download yet.");
            return;
        }
        const transcript = data.messages.map(item => {
            const stamp = new Date(item.created_at).toLocaleString();
            return `[${stamp}] ${item.role === "user" ? "You" : "RecallAI"}:\n${item.message}`;
        }).join("\n\n");
        const url = URL.createObjectURL(new Blob([transcript], { type: "text/plain;charset=utf-8" }));
        const link = document.createElement("a");
        link.href = url;
        link.download = "recallai-conversation.txt";
        link.click();
        window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) {
        alert(error.message);
    }
}

function startVoiceInput() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    const status = document.getElementById("voiceStatus");
    if (!SpeechRecognition) {
        if (status) status.textContent = "Voice input isn't supported by this browser. You can type your message instead.";
        return;
    }
    const recognition = new SpeechRecognition();
    recognition.lang = document.getElementById("languageSelect")?.value === "hi" ? "hi-IN" :
        document.getElementById("languageSelect")?.value === "kn" ? "kn-IN" : "en-IN";
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;
    recognition.onstart = () => { if (status) status.textContent = "Listening…"; };
    recognition.onresult = event => {
        const input = document.getElementById("chatInput");
        if (input) {
            input.value = event.results[0][0].transcript;
            input.focus();
        }
        if (status) status.textContent = "Voice note ready. Press Send when you’re happy with it.";
    };
    recognition.onerror = () => { if (status) status.textContent = "I couldn't hear that clearly. Try again or type your message."; };
    recognition.onend = () => { if (status?.textContent === "Listening…") status.textContent = ""; };
    recognition.start();
}

function addTypingIndicator() {
    const row = document.createElement("div");
    row.className = "message bot typing-message";
    row.id = "typingIndicator";
    const avatar = document.createElement("div");
    avatar.className = "avatar";
    avatar.textContent = "R";
    const bubble = document.createElement("div");
    bubble.className = "bubble typing-bubble";
    bubble.setAttribute("aria-label", "RecallAI is typing");
    bubble.innerHTML = "<span></span><span></span><span></span>";
    row.append(avatar, bubble);
    document.getElementById("chatMessages")?.appendChild(row);
    scrollChat();
}

function removeTypingIndicator() {
    document.getElementById("typingIndicator")?.remove();
}

function showLoggedInUser(user) {
    document.getElementById("welcomeSection")?.classList.add("hidden");
    document.getElementById("userArea")?.classList.remove("hidden");

    document.getElementById("todayJournalCard")?.classList.remove("hidden");
    void loadTodayJournal();

    const display = document.getElementById("usernameDisplay");
    if (display) display.textContent = user.username;
}

async function createUser() {
    const input = document.getElementById("username");
    const username = input?.value.trim();

    if (!username) {
        alert("Please enter your username first.");
        input?.focus();
        return;
    }

    try {
        const response = await fetch("/api/user", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username })
        });

        const data = await response.json();

        if (!data.success) {
            alert(data.message || "Could not create user.");
            return;
        }

        showLoggedInUser(data.user);

        await fetch("/api/session/start", { method: "POST" });
        await loadChatHistory();

        document.getElementById("chatMessages")?.replaceChildren();
        addBotMessage(`Welcome, ${data.user.username}! Add a note about today above, ask me anything, or ask what your saved journal says about earlier days.`);
    } catch (error) {
        console.error(error);
        alert("Could not connect to RecallAI. Check that Flask is running.");
    }
}

function setActiveNav(name) {
    document.querySelectorAll("[data-nav]").forEach(button => {
        button.classList.toggle("active", button.dataset.nav === name);
    });
}

function showChat() {
    document.getElementById("chatSection")?.classList.remove("hidden");
    document.getElementById("challengeSection")?.classList.add("hidden");
    document.getElementById("journalSection")?.classList.add("hidden");
    const loggedIn = !document.getElementById("userArea")?.classList.contains("hidden");
    document.getElementById("todayJournalCard")?.classList.toggle("hidden", !loggedIn);
    setActiveNav("chat");
}

async function showJournal() {
    const userResponse = await fetch("/api/user");
    const userData = await userResponse.json();
    if (!userData.success || !userData.user) {
        alert("Please enter your username first.");
        document.getElementById("username")?.focus();
        return;
    }
    document.getElementById("chatSection")?.classList.add("hidden");
    document.getElementById("todayJournalCard")?.classList.add("hidden");
    document.getElementById("challengeSection")?.classList.add("hidden");
    document.getElementById("journalSection")?.classList.remove("hidden");
    setActiveNav("journal");
    await loadJournalEntries();
}

function localDateISO() {
    const now = new Date();
    now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
    return now.toISOString().slice(0, 10);
}

async function loadTodayJournal() {
    const container = document.getElementById("todayJournalEntries");
    const count = document.getElementById("todayJournalCount");
    if (!container) return;
    try {
        const response = await fetch(`/api/journal?date=${encodeURIComponent(localDateISO())}`);
        const data = await response.json();
        if (!response.ok || !data.success) throw new Error(data.message || "Could not load today’s notes.");
        container.replaceChildren();
        if (count) count.textContent = `${data.entries.length} ${data.entries.length === 1 ? "note" : "notes"}`;
        if (!data.entries.length) {
            const empty = document.createElement("p");
            empty.className = "today-journal-empty";
            empty.textContent = "Nothing saved yet. Add a quick note above, or tell me about your day in chat.";
            container.appendChild(empty);
            return;
        }
        data.entries.forEach(entry => {
            const note = document.createElement("div");
            note.className = "today-journal-note";
            note.textContent = entry.content;
            container.appendChild(note);
        });
    } catch (error) {
        if (count) count.textContent = "Not available";
        container.replaceChildren();
        const notice = document.createElement("p");
        notice.className = "today-journal-empty";
        notice.textContent = "Could not load today’s notes. Try again in a moment.";
        container.appendChild(notice);
        console.error("Today journal loading error:", error);
    }
}

async function saveTodayJournalEntry(event) {
    event.preventDefault();
    const content = document.getElementById("todayJournalContent");
    const status = document.getElementById("todayJournalStatus");
    const note = content?.value.trim();
    if (!note) return;
    try {
        const response = await fetch("/api/journal", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ date: localDateISO(), content: note })
        });
        const data = await response.json();
        if (!response.ok || !data.success) throw new Error(data.message || "Could not save today’s note.");
        content.value = "";
        if (status) status.textContent = "Saved to today’s journal. You can edit or remove it from the timeline.";
        await loadTodayJournal();
        if (!document.getElementById("journalSection")?.classList.contains("hidden")) {
            await loadJournalEntries();
        }
    } catch (error) {
        if (status) status.textContent = error.message;
    }
}
async function loadJournalEntries() {
    const container = document.getElementById("journalEntries");
    if (!container) return;
    container.innerHTML = '<p class="empty-state">Loading your journal...</p>';
    try {
        const response = await fetch("/api/journal?days=30");
        const data = await response.json();
        if (!response.ok || !data.success) throw new Error(data.message || "Could not load your journal.");
        container.replaceChildren();
        if (!data.entries.length) {
            container.innerHTML = '<p class="empty-state">No saved entries yet. Tell RecallAI what you did today or add an entry above.</p>';
            return;
        }
        data.entries.forEach(entry => container.appendChild(createJournalCard(entry)));
    } catch (error) {
        container.innerHTML = '<p class="empty-state">Could not load your journal. Please refresh and try again.</p>';
        console.error(error);
    }
}

function createJournalCard(entry) {
    const card = document.createElement("article");
    card.className = "journal-entry";
    const heading = document.createElement("div");
    heading.className = "journal-entry-heading";
    const date = document.createElement("time");
    date.dateTime = entry.entry_date;
    date.textContent = entry.entry_date;
    const content = document.createElement("p");
    content.className = "journal-entry-content";
    content.textContent = entry.content;
    const actions = document.createElement("div");
    actions.className = "journal-entry-actions";
    const edit = document.createElement("button");
    edit.type = "button";
    edit.className = "secondary-button";
    edit.textContent = "Edit";
    edit.onclick = () => editJournalCard(card, entry);
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "secondary-button journal-delete";
    remove.textContent = "Delete";
    remove.onclick = () => deleteJournalEntry(entry.id);
    actions.append(edit, remove);
    heading.append(date, actions);
    card.append(heading, content);
    return card;
}

function editJournalCard(card, entry) {
    card.replaceChildren();
    const form = document.createElement("form");
    form.className = "journal-edit-form";
    const date = document.createElement("input");
    date.type = "date";
    date.value = entry.entry_date;
    date.required = true;
    const content = document.createElement("textarea");
    content.rows = 3;
    content.maxLength = 4000;
    content.value = entry.content;
    content.required = true;
    const actions = document.createElement("div");
    actions.className = "journal-entry-actions";
    const save = document.createElement("button");
    save.type = "submit";
    save.className = "primary-button";
    save.textContent = "Save changes";
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "secondary-button";
    cancel.textContent = "Cancel";
    cancel.onclick = () => card.replaceWith(createJournalCard(entry));
    actions.append(save, cancel);
    form.append(date, content, actions);
    form.onsubmit = async event => {
        event.preventDefault();
        try {
            const response = await fetch(`/api/journal/${entry.id}`, {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ date: date.value, content: content.value.trim() })
            });
            const data = await response.json();
            if (!response.ok || !data.success) throw new Error(data.message || "Could not update entry.");
            card.replaceWith(createJournalCard(data.entry));
        } catch (error) {
            alert(error.message);
        }
    };
    card.appendChild(form);
    content.focus();
}

async function deleteJournalEntry(id) {
    if (!window.confirm("Delete this journal entry?")) return;
    try {
        const response = await fetch(`/api/journal/${id}`, { method: "DELETE" });
        const data = await response.json();
        if (!response.ok || !data.success) throw new Error(data.message || "Could not delete entry.");
        await loadJournalEntries();
    } catch (error) {
        alert(error.message);
    }
}

async function saveJournalEntry(event) {
    event.preventDefault();
    const date = document.getElementById("journalDate");
    const content = document.getElementById("journalContent");
    const status = document.getElementById("journalStatus");
    try {
        const response = await fetch("/api/journal", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ date: date.value, content: content.value.trim() })
        });
        const data = await response.json();
        if (!response.ok || !data.success) throw new Error(data.message || "Could not save entry.");
        content.value = "";
        status.textContent = `Saved for ${data.entry.entry_date}.`;
        await loadJournalEntries();
    } catch (error) {
        status.textContent = error.message;
    }
}

async function practice() {
    const userResponse = await fetch("/api/user");
    const userData = await userResponse.json();

    if (!userData.success || !userData.user) {
        alert("Please enter your username first.");
        document.getElementById("username")?.focus();
        return;
    }

    window.location.href = "/challenge";
}

function openDashboard() {
    fetch("/api/user")
        .then(response => response.json())
        .then(data => {
            if (!data.success || !data.user) {
                alert("Please enter your username first.");
                document.getElementById("username")?.focus();
                return;
            }
            window.location.href = "/dashboard";
        })
        .catch(() => alert("Could not check your session."));
}

async function sendMessage() {
    const input = document.getElementById("chatInput");
    const message = input?.value.trim();

    if (!message) return;

    let userData;
    try {
        const userResponse = await fetch("/api/user");
        userData = await userResponse.json();
    } catch (error) {
        addBotMessage("I can't reach RecallAI right now. Check that the app is still running, then reload this page.");
        return;
    }

    if (!userData.success || !userData.user) {
        alert("Please enter your username first.");
        document.getElementById("username")?.focus();
        return;
    }

    addUserMessage(message);
    input.value = "";
    addTypingIndicator();

    try {
        const response = await fetch("/api/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message })
        });

        let data;
        try {
            data = await response.json();
        } catch {
            throw new Error(`RecallAI returned an unexpected response (HTTP ${response.status}). Please reload the app and try again.`);
        }
        removeTypingIndicator();

        if (!response.ok || !data.success) {
            addBotMessage(data.message || "Something went wrong.");
            return;
        }

        addBotMessage(data.response.message, null, data.response.citations || []);

        if (data.response.intent === "journal_saved") {
            await loadTodayJournal();
            if (!document.getElementById("journalSection")?.classList.contains("hidden")) await loadJournalEntries();
        }

        if (data.response.action === "practice") {
            setTimeout(practice, 400);
        } else if (data.response.action === "progress") {
            setTimeout(openDashboard, 400);
        }
    } catch (error) {
        removeTypingIndicator();
        console.error(error);
        addBotMessage(error.message || "I couldn't reach RecallAI. Check that the app is running and try again.");
    }
}

function sendQuickMessage(message) {
    const input = document.getElementById("chatInput");
    if (!input) return;
    input.value = message;
    sendMessage();
}

function handleChatKey(event) {
    if (event.key === "Enter") sendMessage();
}

function addUserMessage(message, createdAt = null) {
    const container = document.getElementById("chatMessages");
    if (!container) return;

    const row = document.createElement("div");
    row.className = "message user";

    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.textContent = message;

    const time = document.createElement("time");
    time.className = "message-time";
    time.textContent = formatMessageTime(createdAt);
    time.dateTime = createdAt || new Date().toISOString();
    bubble.appendChild(time);

    row.appendChild(bubble);
    container.appendChild(row);
    scrollChat();
}

function addBotMessage(message, createdAt = null, citations = []) {
    const container = document.getElementById("chatMessages");
    if (!container) return;

    const row = document.createElement("div");
    row.className = "message bot";

    const avatar = document.createElement("div");
    avatar.className = "avatar";
    avatar.textContent = "R";

    const bubble = document.createElement("div");
    bubble.className = "bubble";

    const label = document.createElement("strong");
    label.textContent = "RecallAI";

    const text = document.createElement("div");
    text.className = "assistant-response";
    renderAssistantMarkdown(text, message);

    bubble.append(label, text);
    if (citations.length) {
        const sources = document.createElement("div");
        sources.className = "message-sources";
        const caption = document.createElement("span");
        caption.textContent = "Sources";
        sources.appendChild(caption);
        citations.forEach(citation => {
            try {
                const url = new URL(citation.url);
                if (url.protocol !== "https:") return;
                const link = document.createElement("a");
                link.href = url.href;
                link.target = "_blank";
                link.rel = "noopener noreferrer";
                link.textContent = citation.title || url.hostname;
                sources.appendChild(link);
            } catch (_) { /* Ignore malformed citation URLs. */ }
        });
        if (sources.querySelector("a")) bubble.appendChild(sources);
    }

    const time = document.createElement("time");
    time.className = "message-time";
    time.textContent = formatMessageTime(createdAt);
    time.dateTime = createdAt || new Date().toISOString();

    bubble.appendChild(time);
    row.append(avatar, bubble);
    container.appendChild(row);
    scrollChat();
}

// Render the small, useful subset of Markdown used in assistant replies using
// DOM nodes (never HTML injection), so bold text and lists look natural while
// untrusted response text remains safe.
function renderAssistantMarkdown(container, source) {
    const normalized = String(source || "")
        .replace(/\\([*_`#$])/g, "$1")
        .replace(/\$([A-Za-z0-9_()+*/. -]+)\$/g, (_, formula) => formula.replace(/([A-Za-z)])_([0-9]+)/g, (_, base, digits) => {
            const subscripts = { "0": "₀", "1": "₁", "2": "₂", "3": "₃", "4": "₄", "5": "₅", "6": "₆", "7": "₇", "8": "₈", "9": "₉" };
            return base + [...digits].map(digit => subscripts[digit]).join("");
        }));
    const lines = normalized.split(/\r?\n/);
    let list = null;

    const flushList = () => {
        if (list) container.appendChild(list);
        list = null;
    };
    lines.forEach(line => {
        const trimmed = line.trim();
        if (!trimmed) { flushList(); return; }
        const bullet = trimmed.match(/^(?:[-*•])\s+(.+)$/);
        const numbered = trimmed.match(/^\d+[.)]\s+(.+)$/);
        if (bullet || numbered) {
            const kind = numbered ? "ol" : "ul";
            if (!list || list.tagName.toLowerCase() !== kind) {
                flushList();
                list = document.createElement(kind);
            }
            const item = document.createElement("li");
            appendAssistantInline(item, (bullet || numbered)[1]);
            list.appendChild(item);
            return;
        }
        flushList();
        const heading = trimmed.match(/^#{1,3}\s+(.+)$/);
        const paragraph = document.createElement(heading ? "p" : "p");
        if (heading) paragraph.className = "assistant-heading";
        appendAssistantInline(paragraph, heading ? heading[1] : trimmed);
        container.appendChild(paragraph);
    });
    flushList();
}

function appendAssistantInline(parent, value) {
    const pattern = /(\*\*([^*]+)\*\*|__([^_]+)__|\*([^*]+)\*|_([^_]+)_|`([^`]+)`)/g;
    let cursor = 0;
    let match;
    while ((match = pattern.exec(value)) !== null) {
        if (match.index > cursor) parent.appendChild(document.createTextNode(value.slice(cursor, match.index)));
        const isStrong = match[2] !== undefined || match[3] !== undefined;
        const el = document.createElement(match[6] !== undefined ? "code" : (isStrong ? "strong" : "em"));
        el.textContent = match[2] ?? match[3] ?? match[4] ?? match[5] ?? match[6];
        parent.appendChild(el);
        cursor = pattern.lastIndex;
    }
    if (cursor < value.length) parent.appendChild(document.createTextNode(value.slice(cursor)));
}

function formatMessageTime(value) {
    const timestamp = value ? new Date(value) : new Date();
    return timestamp.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function scrollChat() {
    const container = document.getElementById("chatMessages");
    if (container) container.scrollTop = container.scrollHeight;
}

async function startChallenge() {
    clearTimeout(challengeTimer);

    const content = document.getElementById("challengeContent");
    if (content) content.innerHTML = "<p>Preparing your challenge...</p>";

    try {
        const response = await fetch("/api/challenge/start", {
            method: "POST"
        });

        const data = await response.json();

        if (!data.success) {
            alert(data.message || "Could not start the challenge.");
            window.location.href = "/";
            return;
        }

        currentChallenge = data.challenge;
        currentChallengeId = data.challenge_id;
        renderChallenge();
    } catch (error) {
        console.error(error);
        alert("Could not load the challenge. Check that Flask is running.");
    }
}

function renderChallenge() {
    const challenge = currentChallenge;
    const title = document.getElementById("challengeTitle");
    const badge = document.getElementById("difficultyBadge");

    if (!challenge) return;

    if (title) {
        title.textContent =
            challenge.type.charAt(0).toUpperCase() +
            challenge.type.slice(1) + " Recall";
    }

    if (badge) badge.textContent = `Level ${challenge.difficulty}`;

    if (challenge.type === "word") renderWordChallenge();
    else if (challenge.type === "number") renderNumberChallenge();
    else if (challenge.type === "story") renderStoryChallenge();
}

function renderWordChallenge() {
    const content = document.getElementById("challengeContent");

    content.innerHTML = `
        <p class="challenge-instruction">Memorize these words before they disappear.</p>
        <div id="memoryItems" class="memory-items"></div>
        <p id="timerText" class="timer-text"></p>
        <button id="readyButton" class="primary-button" disabled>Loading timer...</button>
    `;

    const items = document.getElementById("memoryItems");
    currentChallenge.items.forEach(word => {
        const span = document.createElement("span");
        span.className = "memory-item";
        span.textContent = word;
        items.appendChild(span);
    });

    beginMemoryTimer();
}

function renderNumberChallenge() {
    const content = document.getElementById("challengeContent");

    content.innerHTML = `
        <p class="challenge-instruction">Memorize this number sequence in order.</p>
        <div id="memoryItems" class="number-sequence"></div>
        <p id="timerText" class="timer-text"></p>
        <button id="readyButton" class="primary-button" disabled>Loading timer...</button>
    `;

    const items = document.getElementById("memoryItems");
    currentChallenge.items.forEach(number => {
        const span = document.createElement("span");
        span.textContent = number;
        items.appendChild(span);
    });

    beginMemoryTimer();
}

function beginMemoryTimer() {
    let remaining = Number(currentChallenge.display_time) || 8;
    const timerText = document.getElementById("timerText");
    const button = document.getElementById("readyButton");

    button.disabled = true;
    button.textContent = "Memorize the information...";

    const tick = () => {
        if (timerText) timerText.textContent = `Time remaining: ${remaining} seconds`;

        if (remaining <= 0) {
            clearTimeout(challengeTimer);

            const items = document.getElementById("memoryItems");
            if (items) items.classList.add("hidden");

            if (timerText) timerText.textContent = "Time's up! Recall what you remember.";

            button.disabled = false;
            button.textContent = "Enter My Answer";
            button.onclick = () => {
                if (currentChallenge.type === "word") renderWordAnswer();
                else renderNumberAnswer();
            };
            return;
        }

        remaining--;
        challengeTimer = setTimeout(tick, 1000);
    };

    tick();
}

function renderWordAnswer() {
    document.getElementById("challengeContent").innerHTML = `
        <p class="challenge-instruction">Enter the words you remember, separated by commas or spaces.</p>
        <input id="wordAnswer" class="answer-input" placeholder="Example: apple, river, chair">
        <button class="primary-button" onclick="submitWordAnswer()">Submit Answer</button>
    `;
    document.getElementById("wordAnswer").focus();
}

function renderNumberAnswer() {
    document.getElementById("challengeContent").innerHTML = `
        <p class="challenge-instruction">Enter the sequence in the original order.</p>
        <input id="numberAnswer" class="answer-input" inputmode="numeric" placeholder="Example: 4 8 2 9">
        <button class="primary-button" onclick="submitNumberAnswer()">Submit Answer</button>
    `;
    document.getElementById("numberAnswer").focus();
}

function renderStoryChallenge() {
    const content = document.getElementById("challengeContent");

    const instruction = document.createElement("p");
    instruction.className = "challenge-instruction";
    instruction.textContent = "Read and remember the story. Questions appear after you continue.";

    const story = document.createElement("div");
    story.className = "story-box";
    story.textContent = currentChallenge.story;

    const button = document.createElement("button");
    button.className = "primary-button";
    button.textContent = "I'm Ready";
    button.onclick = renderStoryQuestions;

    content.replaceChildren(instruction, story, button);
}

function renderStoryQuestions() {
    const content = document.getElementById("challengeContent");
    content.innerHTML = `
        <p class="challenge-instruction">Answer these questions from memory.</p>
        <div id="storyQuestions" class="story-questions"></div>
        <button class="primary-button" onclick="submitStoryAnswer()">Submit Answers</button>
    `;

    const container = document.getElementById("storyQuestions");

    (currentChallenge.questions || []).forEach((question, index) => {
        const group = document.createElement("div");
        group.className = "question";

        const label = document.createElement("label");
        label.textContent = `${index + 1}. ${question.question}`;

        const input = document.createElement("input");
        input.className = "answer-input story-answer";
        input.dataset.index = index;
        input.placeholder = "Your answer";

        group.append(label, input);
        container.appendChild(group);
    });
}

function submitWordAnswer() {
    const answer = document.getElementById("wordAnswer")?.value.trim();
    if (!answer) return alert("Enter the words you remember.");
    submitChallenge(answer);
}

function submitNumberAnswer() {
    const answer = document.getElementById("numberAnswer")?.value.trim();
    if (!answer) return alert("Enter the number sequence.");
    submitChallenge(answer);
}

function submitStoryAnswer() {
    const inputs = document.querySelectorAll(".story-answer");
    const answers = Array.from(inputs, input => input.value.trim());

    if (!answers.some(Boolean)) return alert("Answer at least one question.");
    submitChallenge(answers);
}

async function submitChallenge(answer) {
    if (!currentChallengeId) return alert("No active challenge.");

    try {
        const response = await fetch("/api/challenge/submit", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ answer })
        });

        const data = await response.json();

        if (!data.success) {
            alert(data.message || "Could not submit your answer.");
            return;
        }

        clearTimeout(challengeTimer);
        currentChallenge = null;
        currentChallengeId = null;
        renderResult(data);
    } catch (error) {
        console.error(error);
        alert("Could not submit your answer.");
    }
}

function renderResult(data) {
    const content = document.getElementById("challengeContent");
    const result = data.result;
    const skill = data.skill;

    content.innerHTML = `
        <div class="result-screen">
            <span class="result-label">YOUR RESULT</span>
            <h2>${Math.round(result.score)}%</h2>
            <p>You recalled ${result.correct_count} out of ${result.total_count} items correctly.</p>
            <div class="result-details">
                <div>Skill score<strong>${Math.round(skill.skill_score)}%</strong></div>
                <div>Current level<strong>Level ${skill.level}</strong></div>
            </div>
            <button class="primary-button" onclick="startChallenge()">Practice Again</button>
            <button class="secondary-button" onclick="window.location.href='/'">Back to Chat</button>
            <button class="secondary-button" onclick="window.location.href='/dashboard'">View Progress</button>
        </div>
    `;

    if (skill.challenge_type === "word") {
        const feedback = document.createElement("div");
        feedback.className = "word-result-feedback";
        const matched = document.createElement("p");
        matched.textContent = `Matched: ${result.correct.length ? result.correct.join(", ") : "none"}`;
        const missed = document.createElement("p");
        missed.textContent = result.missed.length
            ? `Words to review: ${result.missed.join(", ")}`
            : "You recalled every word!";
        feedback.append(matched, missed);
        content.querySelector(".result-screen")?.appendChild(feedback);
    }
}

async function loadDashboard() {
    try {
        const response = await fetch("/api/dashboard");
        const data = await response.json();

        if (!data.success) {
            alert(data.message || "Please enter your username first.");
            window.location.href = "/";
            return;
        }

document.getElementById("overallScore").textContent =
    data.overall_score === null
        ? "Not enough data yet"
        : `${Math.round(data.overall_score)}%`;

        document.getElementById("attemptCount").textContent = data.attempts;
        document.getElementById("typesCount").textContent = data.skills.length;

        const skillList = document.getElementById("skillList");
        skillList.replaceChildren();

        if (!data.skills.length) {
            skillList.innerHTML = '<p class="empty-state">Complete a challenge to see your skill breakdown.</p>';
        }

        data.skills.forEach(skill => {
            const row = document.createElement("div");
            row.className = "skill-row";

            const info = document.createElement("div");
            info.className = "skill-info";

            const name = document.createElement("strong");
            name.textContent = skill.challenge_type.charAt(0).toUpperCase() + skill.challenge_type.slice(1);

            const detail = document.createElement("span");
            detail.textContent = `Level ${skill.level} · ${skill.attempts} attempts`;
            info.append(name, detail);

            const bar = document.createElement("div");
            bar.className = "skill-bar";

            const fill = document.createElement("div");
            fill.className = "skill-fill";
            fill.style.width = `${Math.max(0, Math.min(100, skill.skill_score))}%`;
            bar.appendChild(fill);

            const score = document.createElement("strong");
            score.textContent = `${Math.round(skill.skill_score)}%`;

            row.append(info, bar, score);
            skillList.appendChild(row);
        });

        const attemptList = document.getElementById("attemptList");
        attemptList.replaceChildren();

        if (!data.recent_attempts.length) {
            attemptList.innerHTML = '<p class="empty-state">No completed challenges yet.</p>';
        }

        data.recent_attempts.forEach(attempt => {
            const row = document.createElement("div");
            row.className = "attempt-row";

            const info = document.createElement("div");
            const name = document.createElement("strong");
            name.textContent = `${attempt.challenge_type.charAt(0).toUpperCase() + attempt.challenge_type.slice(1)} Recall`;
            const date = document.createElement("span");
            date.textContent = new Date(attempt.created_at).toLocaleString();
            info.append(name, date);

            const score = document.createElement("strong");
            score.textContent = `${Math.round(attempt.score)}%`;

            row.append(info, score);
            attemptList.appendChild(row);
        });
    } catch (error) {
        console.error(error);
        alert("Could not load your progress.");
    }
}
const recallTranslations = {
    en: {
        "RecallAI Journal & Chat": "RecallAI Journal & Chat",
        "Your day, your questions, your memories — all in one place.": "Your day, your questions, your memories — all in one place.",
        "Today & Chat": "Today & Chat",
        "A little note for today": "A little note for today",
        "Capture the moments you want to remember. Ask RecallAI about saved days whenever you like.": "Capture the moments you want to remember. Ask RecallAI about saved days whenever you like.",
        "Open timeline": "Open timeline",
        "What would you like to remember about today?": "What would you like to remember about today?",
        "Save today’s note": "Save today’s note",
        "Today so far": "Today so far",
        "OPEN-ENDED AI CHAT": "OPEN-ENDED AI CHAT",
        "Give RecallAI its answer engine": "Give RecallAI its answer engine",
        "AI answers are ready · journal recalls use saved entries": "AI answers are ready · journal recalls use saved entries",
        "Journal, quizzes & tips work · add an API key for broad answers": "Journal, quizzes & tips work · add an API key for broad answers",
        "Memory Companion": "Memory Companion",
        "Practice, learn, and track your progress.": "Practice, learn, and track your progress.",
        "Let's train your memory.": "Let's train your memory.",
        "Enter a username to begin your personal practice session.": "Enter a username to begin your personal practice session.",
        "Continue": "Continue",
        "Start a challenge": "Start a challenge",
        "My progress": "My progress",
        "Challenge types": "Challenge types",
        "Ask RecallAI something...": "Ask RecallAI something...",
        "Send": "Send",
        "Progress dashboard": "Progress dashboard",
        "Overall skill score": "Overall skill score",
        "Challenges completed": "Challenges completed",
        "Skill breakdown": "Skill breakdown",
        "Recent attempts": "Recent attempts",
        "Start a challenge": "Start a challenge",
        "Not enough data yet": "Not enough data yet",
        "Journal": "Journal",
        "Daily journal": "Daily journal",
        "YOUR PERSONAL TIMELINE": "YOUR PERSONAL TIMELINE",
        "What did you do?": "What did you do?",
        "Entry date": "Entry date",
        "Save journal entry": "Save journal entry",
        "Recent entries": "Recent entries",
        "Summarize my past few days": "Summarize my past few days",
        "What did I do yesterday?": "What did I do yesterday?",
        "RecallAI is ready": "RecallAI is ready",
        "Your conversation is saved locally": "Your conversation is saved locally",
        "Download": "Download",
        "New chat": "New chat",
        "Quick quiz": "Quick quiz",
        "Memory tip": "Memory tip",
        "What can you do?": "What can you do?",
        "Speak your message": "Speak your message"
    },
    hi: {
        "RecallAI Journal & Chat": "RecallAI डायरी और चैट",
        "Your day, your questions, your memories — all in one place.": "आपका दिन, आपके सवाल और आपकी यादें — सब एक ही जगह।",
        "Today & Chat": "आज और चैट",
        "A little note for today": "आज के लिए एक छोटी-सी डायरी",
        "Capture the moments you want to remember. Ask RecallAI about saved days whenever you like.": "वे पल लिखें जिन्हें आप याद रखना चाहते हैं। सहेजे गए दिनों के बारे में कभी भी पूछें।",
        "Open timeline": "समयरेखा खोलें",
        "What would you like to remember about today?": "आज के बारे में आप क्या याद रखना चाहेंगे?",
        "Save today’s note": "आज की टिप्पणी सहेजें",
        "Today so far": "आज अब तक",
        "OPEN-ENDED AI CHAT": "खुली AI चैट",
        "Give RecallAI its answer engine": "RecallAI के लिए उत्तर सेवा जोड़ें",
        "AI answers are ready · journal recalls use saved entries": "AI उत्तर तैयार हैं · डायरी के जवाब सहेजी गई प्रविष्टियों से मिलते हैं",
        "Journal, quizzes & tips work · add an API key for broad answers": "डायरी, क्विज़ और सुझाव उपलब्ध हैं · सामान्य सवालों के लिए API कुंजी जोड़ें",
        "Memory Companion": "स्मृति सहायक",
        "Practice, learn, and track your progress.": "अभ्यास करें, सीखें और अपनी प्रगति देखें।",
        "Let's train your memory.": "आइए अपनी याददाश्त का अभ्यास करें।",
        "Enter a username to begin your personal practice session.": "अभ्यास शुरू करने के लिए अपना उपयोगकर्ता नाम दर्ज करें।",
        "Continue": "जारी रखें",
        "Start a challenge": "अभ्यास शुरू करें",
        "My progress": "मेरी प्रगति",
        "Challenge types": "अभ्यास के प्रकार",
        "Ask RecallAI something...": "RecallAI से कुछ पूछें...",
        "Send": "भेजें",
        "Progress dashboard": "प्रगति डैशबोर्ड",
        "Overall skill score": "कुल कौशल स्कोर",
        "Challenges completed": "पूरे किए गए अभ्यास",
        "Skill breakdown": "कौशल विवरण",
        "Recent attempts": "हाल के प्रयास",
        "Not enough data yet": "अभी पर्याप्त डेटा नहीं है",
        "Journal": "डायरी",
        "Daily journal": "दैनिक डायरी",
        "YOUR PERSONAL TIMELINE": "आपकी व्यक्तिगत समयरेखा",
        "What did you do?": "आपने क्या किया?",
        "Entry date": "प्रविष्टि की तारीख",
        "Save journal entry": "डायरी प्रविष्टि सहेजें",
        "Recent entries": "हाल की प्रविष्टियाँ",
        "Summarize my past few days": "मेरे पिछले कुछ दिनों का सारांश दें",
        "What did I do yesterday?": "मैंने कल क्या किया?",
        "RecallAI is ready": "RecallAI तैयार है",
        "Your conversation is saved locally": "आपकी बातचीत यहाँ सहेजी जाती है",
        "Download": "डाउनलोड",
        "New chat": "नई चैट",
        "Quick quiz": "त्वरित प्रश्नोत्तरी",
        "Memory tip": "याददाश्त सुझाव",
        "What can you do?": "आप क्या कर सकते हैं?",
        "Speak your message": "अपना संदेश बोलें"
    },
    kn: {
        "RecallAI Journal & Chat": "RecallAI ದಿನಚರಿ ಮತ್ತು ಚಾಟ್",
        "Your day, your questions, your memories — all in one place.": "ನಿಮ್ಮ ದಿನ, ಪ್ರಶ್ನೆಗಳು ಮತ್ತು ನೆನಪುಗಳು — ಒಂದೇ ಸ್ಥಳದಲ್ಲಿ.",
        "Today & Chat": "ಇಂದು ಮತ್ತು ಚಾಟ್",
        "A little note for today": "ಇಂದಿನ ಒಂದು ಚಿಕ್ಕ ಟಿಪ್ಪಣಿ",
        "Capture the moments you want to remember. Ask RecallAI about saved days whenever you like.": "ನೀವು ನೆನಪಿಡಲು ಬಯಸುವ ಕ್ಷಣಗಳನ್ನು ದಾಖಲಿಸಿ. ಉಳಿಸಿದ ದಿನಗಳ ಬಗ್ಗೆ ಯಾವಾಗ ಬೇಕಾದರೂ ಕೇಳಿ.",
        "Open timeline": "ಕಾಲರೇಖೆ ತೆರೆಯಿರಿ",
        "What would you like to remember about today?": "ಇಂದಿನ ಬಗ್ಗೆ ನೀವು ಏನು ನೆನಪಿಡಲು ಬಯಸುತ್ತೀರಿ?",
        "Save today’s note": "ಇಂದಿನ ಟಿಪ್ಪಣಿ ಉಳಿಸಿ",
        "Today so far": "ಇಂದು ಇಲ್ಲಿಯವರೆಗೆ",
        "OPEN-ENDED AI CHAT": "ಮುಕ್ತ AI ಚಾಟ್",
        "Give RecallAI its answer engine": "RecallAIಗೆ ಉತ್ತರ ಸೇವೆ ಸೇರಿಸಿ",
        "AI answers are ready · journal recalls use saved entries": "AI ಉತ್ತರಗಳು ಸಿದ್ಧ · ದಿನಚರಿ ಉತ್ತರಗಳು ಉಳಿಸಿದ ದಾಖಲೆಗಳಿಂದ",
        "Journal, quizzes & tips work · add an API key for broad answers": "ದಿನಚರಿ, ಕ್ವಿಜ್ ಮತ್ತು ಸಲಹೆಗಳು ಲಭ್ಯ · ಸಾಮಾನ್ಯ ಉತ್ತರಗಳಿಗೆ API ಕೀ ಸೇರಿಸಿ",
        "Memory Companion": "ಸ್ಮರಣಾ ಸಹಾಯಕ",
        "Practice, learn, and track your progress.": "ಅಭ್ಯಾಸ ಮಾಡಿ, ಕಲಿಯಿರಿ ಮತ್ತು ನಿಮ್ಮ ಪ್ರಗತಿಯನ್ನು ನೋಡಿ.",
        "Let's train your memory.": "ನಿಮ್ಮ ನೆನಪಿನ ಶಕ್ತಿಯನ್ನು ಅಭ್ಯಾಸ ಮಾಡೋಣ.",
        "Enter a username to begin your personal practice session.": "ಅಭ್ಯಾಸ ಪ್ರಾರಂಭಿಸಲು ನಿಮ್ಮ ಬಳಕೆದಾರ ಹೆಸರನ್ನು ನಮೂದಿಸಿ.",
        "Continue": "ಮುಂದುವರಿಸಿ",
        "Start a challenge": "ಅಭ್ಯಾಸ ಪ್ರಾರಂಭಿಸಿ",
        "My progress": "ನನ್ನ ಪ್ರಗತಿ",
        "Challenge types": "ಅಭ್ಯಾಸದ ವಿಧಗಳು",
        "Ask RecallAI something...": "RecallAI ಅನ್ನು ಏನಾದರೂ ಕೇಳಿ...",
        "Send": "ಕಳುಹಿಸಿ",
        "Progress dashboard": "ಪ್ರಗತಿ ಡ್ಯಾಶ್‌ಬೋರ್ಡ್",
        "Overall skill score": "ಒಟ್ಟು ಕೌಶಲ್ಯ ಅಂಕ",
        "Challenges completed": "ಪೂರ್ಣಗೊಂಡ ಅಭ್ಯಾಸಗಳು",
        "Skill breakdown": "ಕೌಶಲ್ಯ ವಿವರ",
        "Recent attempts": "ಇತ್ತೀಚಿನ ಪ್ರಯತ್ನಗಳು",
        "Not enough data yet": "ಇನ್ನೂ ಸಾಕಷ್ಟು ಮಾಹಿತಿ ಇಲ್ಲ",
        "Journal": "ದಿನಚರಿ",
        "Daily journal": "ದೈನಂದಿನ ದಿನಚರಿ",
        "YOUR PERSONAL TIMELINE": "ನಿಮ್ಮ ವೈಯಕ್ತಿಕ ಕಾಲರೇಖೆ",
        "What did you do?": "ನೀವು ಏನು ಮಾಡಿದ್ದೀರಿ?",
        "Entry date": "ದಿನಾಂಕ",
        "Save journal entry": "ದಿನಚರಿ ದಾಖಲೆಯನ್ನು ಉಳಿಸಿ",
        "Recent entries": "ಇತ್ತೀಚಿನ ದಾಖಲೆಗಳು",
        "Summarize my past few days": "ನನ್ನ ಕಳೆದ ಕೆಲವು ದಿನಗಳ ಸಾರಾಂಶ ನೀಡಿ",
        "What did I do yesterday?": "ನಾನು ನಿನ್ನೆ ಏನು ಮಾಡಿದೆ?",
        "RecallAI is ready": "RecallAI ಸಿದ್ಧವಾಗಿದೆ",
        "Your conversation is saved locally": "ನಿಮ್ಮ ಸಂಭಾಷಣೆ ಇಲ್ಲಿ ಉಳಿಸಲಾಗಿದೆ",
        "Download": "ಡೌನ್‌ಲೋಡ್",
        "New chat": "ಹೊಸ ಚಾಟ್",
        "Quick quiz": "ತ್ವರಿತ ರಸಪ್ರಶ್ನೆ",
        "Memory tip": "ನೆನಪಿನ ಸಲಹೆ",
        "What can you do?": "ನೀವು ಏನು ಮಾಡಬಹುದು?",
        "Speak your message": "ನಿಮ್ಮ ಸಂದೇಶವನ್ನು ಹೇಳಿ"
    }
};

function setLanguage(language) {
    if (!recallTranslations[language]) language = "en";

    localStorage.setItem("recallai-language", language);

    const translations = recallTranslations[language];

    // Translate exact text nodes without removing their child elements.
    const walker = document.createTreeWalker(
        document.body,
        NodeFilter.SHOW_TEXT
    );

    let node;
    while ((node = walker.nextNode())) {
        const original = node.nodeValue.trim();
        if (!original) continue;

        const translated = translations[original];
        if (translated) {
            node.nodeValue = node.nodeValue.replace(original, translated);
        }
    }

    const chatInput = document.getElementById("chatInput");
    if (chatInput) {
        chatInput.placeholder = translations["Ask RecallAI something..."] ||
            "Ask RecallAI something...";
    }

    const languageSelect = document.getElementById("languageSelect");
    if (languageSelect) languageSelect.value = language;
}

function toggleTheme() {
    const dark = document.body.classList.toggle("dark-theme");
    localStorage.setItem("recallai-theme", dark ? "dark" : "light");
}

function loadAppearanceSettings() {
    const language = localStorage.getItem("recallai-language") || "en";
    const theme = localStorage.getItem("recallai-theme") || "light";

    if (theme === "dark") {
        document.body.classList.add("dark-theme");
    }

    const selector = document.getElementById("languageSelect");
    if (selector) selector.value = language;

    setLanguage(language);
}

document.addEventListener("DOMContentLoaded", loadAppearanceSettings);
