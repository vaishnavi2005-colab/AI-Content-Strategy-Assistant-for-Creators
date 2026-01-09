from flask import Flask, request, jsonify, render_template, redirect, url_for, session
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.llms import Ollama
import sqlite3
import re
import markdown


# ---------------- APP CONFIG ----------------
app = Flask(__name__)
app.secret_key = "content_ai_secret"
DB_NAME = "users.db"


# ---------------- DATABASE ----------------
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT
        )
    """)
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            role TEXT,          -- 'user' or 'bot'
            message TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    conn.commit()
    conn.close()

init_db()

def save_message(username, role, message):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO chat_history (username, role, message) VALUES (?, ?, ?)",
        (username, role, message)
    )
    conn.commit()
    conn.close()

# ---------------- VECTOR STORE ----------------
embeddings = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2"
)

vectorstore = FAISS.load_local(
    "vectorstore",
    embeddings,
    allow_dangerous_deserialization=True
)

retriever = vectorstore.as_retriever(search_kwargs={"k": 4})

# ---------------- LLM ----------------
llm = Ollama(
    model="llama3",
    temperature=0.4
)

# ---------------- GENERAL CHAT ----------------
def handle_general_chat(q: str):
    responses = {
        "hi": "Hey 👋 What are you working on today?",
        "hello": "Hello 😊 How can I help?",
        "how are you": "I’m doing great! Ready to help 🚀",
        "what can you do": (
            "I help creators with:\n"
            "- Content ideas\n"
            "- Growth strategies\n"
            "- Platform-specific planning\n"
            "- Consistency and optimization"
        ),
        "thanks": "You’re welcome 😊",
        "thank you": "Happy to help 🙌"
    }
    return responses.get(q.lower())

# ---------------- INTENT DETECTION ----------------
def detect_intent(question: str) -> str:
    q = question.lower()
    if any(w in q for w in ["explain", "detail", "elaborate", "how", "why", "in depth"]):
        return "deep"
    if any(w in q for w in ["list", "tips", "steps", "ideas", "strategies"]):
        return "bullet"
    return "balanced"

# ---------------- CLEAN CONTEXT ----------------
def clean_text(text: str) -> str:
    patterns = [
        r"according to .*?",
        r"this document .*?",
        r"this guide .*?",
        r"from the .*?",
        r"in this pdf .*?",
        r"these guidelines .*?"
    ]
    for p in patterns:
        text = re.sub(p, "", text, flags=re.IGNORECASE)
    return text.strip()

# ---------------- FORMAT RESPONSE ----------------
def format_response(text: str) -> str:
    html = markdown.markdown(
        text.strip(),
        extensions=["extra", "sane_lists"]
    )
    return html

def force_hashtags(text):
    words = re.findall(r'\b[a-zA-Z0-9_]+\b', text)
    hashtags = ["#" + w for w in words if not w.lower().startswith("http")]
    return " ".join(dict.fromkeys(hashtags))

# ---------------- ANSWER GENERATION ----------------
def answer_question(question: str) -> str:
    intent = detect_intent(question)
    docs = retriever.invoke(question)

    context = " ".join(
        clean_text(d.page_content) for d in docs[:3]
    )

    if intent == "detailed":
        prompt = f"""
You are a senior content strategy expert.

MANDATORY STRUCTURE:
1. Start with a short summary (2–3 lines)
2. Then give a detailed explanation
3. Use clear headings
4. Use bullet points where useful
5. Keep paragraphs short and readable

Rules:
- Never mention documents, PDFs, files, or sources
- Never say "according to" or "based on"
- Be confident, human, and clear
- Fully cover the topic

Knowledge you already have:
{context}

User question:
{question}

Answer:
"""

    elif intent == "bullet":
        prompt = f"""
You are a practical content strategist.

Rules:
- Give a bullet-point answer
- Each bullet must be meaningful
- Add short explanations where helpful
- Do not write an essay
- No fluff
- Try to keep same font size for entire text
- Hashtags should begin with '#'

Knowledge you already have:
{context}

User question:
{question}

Answer:
"""

    else:
        prompt = f"""
You are a friendly and intelligent content creation assistant.

Rules:
- Answer clearly and naturally
- Cover all key points
- Balanced length (not short, not verbose)
- Use bullets only if they improve clarity
- Sound human and confident

Knowledge you already have:
{context}

User question:
{question}

Answer:
"""

    raw_answer = llm.invoke(prompt)
    
    if "hashtag" in question.lower():
        return force_hashtags(raw_answer)
    
    return format_response(raw_answer)

# ---------------- AUTH ROUTES ----------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        try:
            conn = sqlite3.connect(DB_NAME)
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO users (username, password) VALUES (?, ?)",
                (email, password)
            )
            conn.commit()
            conn.close()
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            return "Email already registered"

    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM users WHERE username=? AND password=?",
            (email, password)
        )
        user = cur.fetchone()
        conn.close()

        if user:
            session["user"] = email
            session["chat_history"] = []
            return redirect(url_for("home"))

        return "Invalid email or password"

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ---------------- CHAT ROUTES ----------------
@app.route("/")
def home():
    if "user" not in session:
        return redirect(url_for("login"))
    return render_template("chatbot.html", user=session["user"])

@app.route("/ask", methods=["POST"])
def ask():
    if "user" not in session:
        return jsonify({"answer": "Please login first."})

    username = session["user"]
    question = request.json.get("question", "").strip()

    if not question:
        return jsonify({"answer": "Please ask something 🙂"})

    # Save user message
    save_message(username, "user", question)

    general = handle_general_chat(question)
    if general:
        save_message(username, "bot", general)
        return jsonify({"answer": general})

    answer = answer_question(question)

    # Save bot response
    save_message(username, "bot", answer)

    return jsonify({"answer": answer})

@app.route("/history")
def history():
    if "user" not in session:
        return jsonify([])

    username = session["user"]

    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT role, message 
        FROM chat_history 
        WHERE username=?
        ORDER BY timestamp ASC
    """, (username,))
    
    rows = cur.fetchall()
    conn.close()

    return jsonify([
        {"role": r[0], "message": r[1]}
        for r in rows
    ])

@app.route("/new_chat", methods=["POST"])
def new_chat():
    session["chat_history"] = []
    return jsonify({"status": "ok"})


# ---------------- RUN ----------------
if __name__ == "__main__":
    app.run(debug=True)
