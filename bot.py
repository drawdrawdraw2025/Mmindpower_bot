#!/usr/bin/env python3
"""Mmindpower_bot — Telegram bot with Groq AI chat.
Zero-dependency (requests only), long-polling. Run: python3 bot.py
Secrets come from environment: TG_TOKEN, GROQ_KEY
"""
import os, json, time, requests

TOKEN = os.environ["TG_TOKEN"]
GROQ_KEY = os.environ["GROQ_KEY"]
TG = f"https://api.telegram.org/bot{TOKEN}"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "openai/gpt-oss-120b"

WELCOME = (
    "🚀 <b>Welcome to Mmindpower Bot!</b>\n\n"
    "I am your AI-powered assistant. Just send me any message and I'll answer using AI.\n\n"
    "✨ <b>What I can do:</b>\n"
    "• 💬 Answer any question (AI chat)\n"
    "• 📚 Help with study topics\n"
    "• 🧠 Brainstorm ideas\n\n"
    "Type anything below to start chatting 👇"
)
HELP = (
    "❓ <b>Commands</b>\n\n"
    "/start — welcome screen\n"
    "/help — this help\n"
    "/about — about this bot\n"
    "/reset — clear chat memory\n\n"
    "Or simply send any text and the AI will reply. 💬"
)
ABOUT = (
    "🤖 <b>About Mmindpower Bot</b>\n\n"
    "An AI assistant built with the Groq inference engine (Llama 3.3 70B).\n"
    "More abilities coming soon — quizzes, broadcasts and tools. Stay tuned! ⚡"
)
SYSTEM_PROMPT = (
    "You are Mmindpower Bot, a helpful, friendly Telegram assistant. "
    "Answer clearly and concisely. Use short paragraphs; plain text only "
    "(no markdown tables). If asked who made you, say you are Mmindpower Bot."
)

MEM = {}   # chat_id -> list of {role, content}
ADMIN_SEEN = set()

def tg(method, **params):
    try:
        r = requests.post(f"{TG}/{method}", json=params, timeout=60)
        return r.json()
    except Exception as e:
        print("TG error:", e)
        return {}

def send_text(chat_id, text):
    return tg("sendMessage", chat_id=chat_id, text=text, parse_mode="HTML",
              link_preview_options={"is_disabled": True})

def groq_reply(chat_id, text):
    hist = MEM.setdefault(chat_id, [])
    hist.append({"role": "user", "content": text})
    hist = hist[-12:]                      # keep last 12 turns
    MEM[chat_id] = hist
    payload = {
        "model": MODEL,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}] + hist,
        "temperature": 0.7,
        "max_completion_tokens": 2048,
        "reasoning_effort": "low",
    }
    try:
        r = requests.post(GROQ_URL, json=payload, timeout=90,
                          headers={"Authorization": f"Bearer {GROQ_KEY}"})
        data = r.json()
        reply = (data["choices"][0]["message"].get("content") or "").strip()
        if not reply:
            raise ValueError("empty content")
    except Exception as e:
        print("Groq error:", e)
        reply = "⚠️ Sorry, the AI service is busy right now. Please try again in a moment."
        return reply
    hist.append({"role": "assistant", "content": reply})
    return reply

def handle(update):
    msg = update.get("message") or {}
    text = (msg.get("text") or "").strip()
    chat = msg.get("chat") or {}
    chat_id, user = chat.get("id"), msg.get("from") or {}
    if chat_id is None:
        return
    name = user.get("first_name", "friend")
    if chat_id not in ADMIN_SEEN:
        ADMIN_SEEN.add(chat_id)
        print(f"[new user] {user.get('username')} ({chat_id}): {name}")

    cmd = text.split()[0].split("@")[0].lower() if text.startswith("/") else None
    if cmd == "/start":
        send_text(chat_id, f"Hello <b>{name}</b>! 👋\n\n" + WELCOME)
    elif cmd == "/help":
        send_text(chat_id, HELP)
    elif cmd == "/about":
        send_text(chat_id, ABOUT)
    elif cmd == "/reset":
        MEM.pop(chat_id, None)
        send_text(chat_id, "🧹 Chat memory cleared. Fresh start!")
    elif text:
        thinking = tg("sendChatAction", chat_id=chat_id, action="typing")
        reply = groq_reply(chat_id, text)
        send_text(chat_id, reply)

def main():
    me = tg("getMe")
    print("Bot running as", me.get("result", {}).get("username"))
    offset = None
    conflicts = 0
    while True:
        try:
            params = {"timeout": 50, "allowed_updates": ["message"]}
            if offset:
                params["offset"] = offset
            data = requests.post(f"{TG}/getUpdates", json=params, timeout=70).json()
            if not data.get("ok"):
                desc = str(data.get("description", ""))
                if "conflict" in desc.lower():
                    conflicts += 1
                    print("Conflict with another poller", conflicts)
                    if conflicts >= 3:
                        print("Another bot instance is active — exiting.")
                        return
                    time.sleep(5)
                else:
                    print("TG not ok:", desc[:120])
                    time.sleep(3)
                continue
            conflicts = 0
            for up in data.get("result", []):
                offset = up["update_id"] + 1
                try:
                    handle(up)
                except Exception as e:
                    print("handle error:", e)
        except Exception as e:
            print("poll error:", e)
            time.sleep(3)

if __name__ == "__main__":
    main()
