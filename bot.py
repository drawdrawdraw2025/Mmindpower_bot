#!/usr/bin/env python3
"""Mmindpower_bot — Telegram bot: AI chat + Daily Quiz (90 Qs/day, clickable answers).
Zero-dependency (requests only), long-polling. Run: python3 bot.py
Env: TG_TOKEN, GROQ_KEY, GH_TOKEN + REPO (for quiz state persistence on GitHub).
"""
import os, json, time, base64, datetime, requests

TOKEN = os.environ["TG_TOKEN"]
GROQ_KEY = os.environ["GROQ_KEY"]
GH_TOKEN = os.environ.get("GH_TOKEN", "")
REPO = os.environ.get("REPO", "")
TG = f"https://api.telegram.org/bot{TOKEN}"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "openai/gpt-oss-120b"

OWNER_CHAT = 7102918717          # Balu (@Mmindpower1)
DAILY_LIMIT = 90                 # questions per day
SEND_HOUR_START, SEND_HOUR_END = 6, 23   # IST delivery window
IDLE_NEXT_SECS = 10 * 60         # next question if user doesn't answer
ANSWERED_NEXT_SECS = 2 * 60      # next question after user answers
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))

WELCOME = (
    "🚀 <b>Welcome to Mmindpower Bot!</b>\n\n"
    "✨ <b>What I can do:</b>\n"
    "• 📚 <b>Daily Quiz</b> — 90 Talathi/MPSC questions per day with clickable answers & explanations (/quiz)\n"
    "• 💬 AI chat — send any message for an AI answer\n\n"
    "Commands: /quiz /quiz stop /quiz status /help"
)
HELP = (
    "❓ <b>Commands</b>\n\n"
    "/quiz — start/resume daily quiz\n"
    "/quiz stop — pause quiz\n"
    "/quiz status — quiz progress\n"
    "/help — this help\n"
    "/about — about this bot\n"
    "/reset — clear AI chat memory\n\n"
    "Or simply send any text and the AI will reply. 💬"
)
ABOUT = ("🤖 <b>About Mmindpower Bot</b>\n\nAI assistant + Daily Quiz engine.\n"
         "Quiz bank: Talathi MPSC 2026 sets. Powered by Groq. ⚡")
SYSTEM_PROMPT = (
    "You are Mmindpower Bot, a helpful, friendly Telegram assistant. "
    "Answer clearly and concisely. Use short paragraphs; plain text only "
    "(no markdown tables). If asked who made you, say you are Mmindpower Bot."
)

MEM = {}          # chat_id -> AI chat history
QS = None         # quiz state dict
DATA = {}         # set letter -> list of questions
STATE_SHA = None

# ---------------- Telegram helpers ----------------
def tg(method, **params):
    try:
        r = requests.post(f"{TG}/{method}", json=params, timeout=60)
        return r.json()
    except Exception as e:
        print("TG error:", method, e)
        return {}

def send_text(chat_id, text, reply_markup=None):
    p = dict(chat_id=chat_id, text=text, parse_mode="HTML",
             link_preview_options={"is_disabled": True})
    if reply_markup:
        p["reply_markup"] = reply_markup
    return tg("sendMessage", **p)

def edit_text(chat_id, msg_id, text, reply_markup=None):
    p = dict(chat_id=chat_id, message_id=msg_id, text=text, parse_mode="HTML",
             link_preview_options={"is_disabled": True})
    if reply_markup:
        p["reply_markup"] = reply_markup
    return tg("editMessageText", **p)

# ---------------- AI chat ----------------
def groq_reply(chat_id, text):
    hist = MEM.setdefault(chat_id, [])
    hist.append({"role": "user", "content": text})
    hist = hist[-12:]
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
        reply = (r.json()["choices"][0]["message"].get("content") or "").strip()
        if not reply:
            raise ValueError("empty content")
    except Exception as e:
        print("Groq error:", e)
        return "⚠️ Sorry, the AI service is busy right now. Please try again in a moment."
    hist.append({"role": "assistant", "content": reply})
    return reply

# ---------------- Quiz data & state ----------------
def load_data():
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        p = f"quiz_data_{letter}.json"
        if os.path.exists(p):
            DATA[letter] = json.load(open(p, encoding="utf-8"))
    print("Quiz data loaded:", {k: len(v) for k, v in DATA.items()})

def default_state():
    today = datetime.datetime.now(IST).strftime("%Y-%m-%d")
    return {"set": "A", "index": 0, "day": today, "today_sent": 0,
            "next_due": 0, "pending_qid": None, "pending_msg": None,
            "active": True, "total_done": 0}

def gh_get_state():
    global STATE_SHA
    if not (GH_TOKEN and REPO):
        return None
    try:
        r = requests.get(f"https://api.github.com/repos/{REPO}/contents/quiz_state.json",
                         headers={"Authorization": f"Bearer {GH_TOKEN}"}, timeout=30)
        if r.status_code == 404:
            return None
        d = r.json()
        STATE_SHA = d["sha"]
        return json.loads(base64.b64decode(d["content"]))
    except Exception as e:
        print("state load err:", e)
        return None

def gh_save_state():
    global STATE_SHA
    if not (GH_TOKEN and REPO):
        return
    try:
        body = {"message": "quiz state update",
                "content": base64.b64encode(json.dumps(QS).encode()).decode(),
                "branch": "main"}
        if STATE_SHA:
            body["sha"] = STATE_SHA
        r = requests.put(f"https://api.github.com/repos/{REPO}/contents/quiz_state.json",
                         json=body, headers={"Authorization": f"Bearer {GH_TOKEN}"}, timeout=30)
        if r.status_code in (200, 201):
            STATE_SHA = r.json()["content"]["sha"]
        else:
            STATE_SHA = None          # refresh sha next save
            print("state save http", r.status_code, r.text[:120])
    except Exception as e:
        print("state save err:", e)

def save_state():
    gh_save_state()

def qid_of(set_letter, index):
    return f"{set_letter}{index + 1}"

def current_q():
    if not DATA:
        return None
    L = QS["set"]
    while L and L not in DATA:
        L = next_set(L)
    if not L or L not in DATA:
        return None
    if QS["index"] >= len(DATA[L]):
        return None
    return L, QS["index"], DATA[L][QS["index"]]

def next_set(L):
    order = sorted(DATA.keys())
    i = order.index(L) if L in order else -1
    return order[i + 1] if 0 <= i < len(order) - 1 else None

# ---------------- Quiz messages ----------------
def q_text_block(set_letter, index, q):
    mr = q.get("q_marathi", "")
    en = q.get("q_english", "")
    opts = q.get("options", [])
    letters = ["A", "B", "C", "D"]
    opt_lines = "\n".join(f"<b>{letters[i]})</b> {opts[i]}" for i in range(min(4, len(opts))))
    head = (f"📚 <b>Daily Quiz — Set {set_letter}</b>  "
            f"(Q {index + 1}/{len(DATA[set_letter])} • today {QS['today_sent']}/{DAILY_LIMIT})\n\n")
    return head, mr, en, opt_lines

def q_body(set_letter, index, q, with_english=True, limit=3950):
    """Full question text (question + options), optionally with English, kept under limit."""
    head, mr, en, opt_lines = q_text_block(set_letter, index, q)
    body = f"{head}🇮🇳 {mr}\n\n<b>Options:</b>\n{opt_lines}"
    if with_english and en and len(body) + len(en) < limit:
        body += f"\n\n🇬🇧 <i>{en}</i>"
    if len(body) > limit:
        body = body[:limit] + "…"
    return body

def kb_answers(qid):
    return {"inline_keyboard": [[
        {"text": "🅰️ A", "callback_data": f"ans|{qid}|0"},
        {"text": "🅱️ B", "callback_data": f"ans|{qid}|1"}], [
        {"text": "🅲 C", "callback_data": f"ans|{qid}|2"},
        {"text": "🅳 D", "callback_data": f"ans|{qid}|3"}]]}

def kb_explain(qid, next_due_far=True):
    row1 = [{"text": "📖 Show Explanation", "callback_data": f"exp|{qid}"}]
    row2 = [{"text": "▶️ Next question now", "callback_data": f"next|{qid}"}]
    return {"inline_keyboard": [row1, row2]}

def send_question():
    cur = current_q()
    if not cur:
        send_text(OWNER_CHAT, "🎉 <b>All available quiz sets are complete!</b> More sets coming soon.")
        QS["active"] = False
        save_state()
        return False
    L, idx, q = cur
    qid = qid_of(L, idx)
    QS["today_sent"] += 1
    QS["total_done"] += 1
    head, mr, en, opt_lines = q_text_block(L, idx, q)
    body = f"{head}🇮🇳 {mr}\n\n<b>Options:</b>\n{opt_lines}"
    if len(body) + len(en) < 3900:
        body += f"\n\n🇬🇧 <i>{en}</i>"
        en_sent_inside = True
    else:
        en_sent_inside = False
    res = send_text(OWNER_CHAT, body, reply_markup=kb_answers(qid))
    msg_id = (res.get("result") or {}).get("message_id")
    if not en_sent_inside and en:
        send_text(OWNER_CHAT, f"🇬🇧 <i>{en}</i>")
    QS["pending_qid"] = qid
    QS["pending_msg"] = msg_id
    QS["next_due"] = time.time() + IDLE_NEXT_SECS
    save_state()
    print(f"sent {qid} to {OWNER_CHAT}")
    return True

def finalize_pending(time_up=False):
    """Reveal answer on the pending question, keeping the full question visible."""
    cur = current_q()
    if not cur or not QS.get("pending_msg"):
        return
    L, idx, q = cur
    qid = qid_of(L, idx)
    if QS.get("pending_qid") != qid:
        return
    ci = q.get("correct_index", 0)
    letters = ["A", "B", "C", "D"]
    note = "⏰ <b>Time's up!</b> " if time_up else ""
    body = q_body(L, idx, q)
    tail = f"\n\n{note}✅ <b>Correct answer: {letters[ci]}</b>\nTap below for the explanation:"
    if len(body) + len(tail) > 4000:
        body = q_body(L, idx, q, with_english=False)
    edit_text(OWNER_CHAT, QS["pending_msg"],
              body + tail, reply_markup=kb_explain(qid))
    QS["pending_qid"] = None
    QS["pending_msg"] = None

def advance(when=None):
    """Move pointer to next question; cross into next set if needed."""
    L = QS["set"]
    if L in DATA and QS["index"] + 1 < len(DATA[L]):
        QS["index"] += 1
    else:
        nxt = next_set(L)
        if nxt:
            QS["set"] = nxt
            QS["index"] = 0
        else:
            QS["active"] = False
    QS["next_due"] = when if when else time.time()
    QS["pending_qid"] = None
    QS["pending_msg"] = None
    save_state()

# ---------------- Quiz scheduler tick ----------------
def quiz_tick():
    global QS
    if not DATA or QS is None or not QS.get("active"):
        return
    now = datetime.datetime.now(IST)
    today = now.strftime("%Y-%m-%d")
    if today != QS["day"]:
        QS["day"] = today
        QS["today_sent"] = 0
        save_state()
    if QS["today_sent"] >= DAILY_LIMIT:
        return
    if not (SEND_HOUR_START <= now.hour < SEND_HOUR_END):
        return
    if time.time() < QS.get("next_due", 0):
        return
    if QS.get("pending_qid"):
        finalize_pending(time_up=True)
        advance(when=time.time() + 30)
        return
    send_question()

# ---------------- Callbacks & messages ----------------
def handle_callback(cb):
    data = cb.get("data", "")
    chat_id = cb["message"]["chat"]["id"]
    msg_id = cb["message"]["message_id"]
    cur = current_q()
    cur_qid = qid_of(cur[0], cur[1]) if cur else None
    try:
        kind, qid, rest = (data.split("|") + ["", ""])[:3]
    except Exception:
        return
    if kind == "ans":
        if qid != cur_qid:
            tg("answerCallbackQuery", callback_query_id=cb["id"],
               text="This question was already completed.")
            return
        L, idx, q = cur
        chosen = int(rest)
        ci = q.get("correct_index", 0)
        letters = ["A", "B", "C", "D"]
        verdict = ("✅ <b>Correct!</b>" if chosen == ci else
                   f"❌ You chose <b>{letters[chosen]}</b>. Correct answer: <b>{letters[ci]}</b>")
        # Keep the full question visible, append the verdict below it.
        body = q_body(L, idx, q)
        tail = f"\n\n{verdict}\n\nTap below for the explanation:"
        if len(body) + len(tail) > 4000:
            body = q_body(L, idx, q, with_english=False)
        edit_text(chat_id, msg_id, body + tail, reply_markup=kb_explain(qid))
        tg("answerCallbackQuery", callback_query_id=cb["id"],
           text="Correct!" if chosen == ci else f"Correct answer: {letters[ci]}")
        # move pointer to the next question; explanation stays accessible via qid lookup
        advance(when=time.time() + ANSWERED_NEXT_SECS)
        QS["_answered_qid"] = qid
    elif kind == "exp":
        if not cur or qid != cur_qid:
            q = find_by_qid(qid)
        else:
            q = cur[2]
        if q:
            ci = q.get("correct_index", 0)
            letters = ["A", "B", "C", "D"]
            exp = q.get("explanation_marathi", "")
            ev = q.get("evidence", "")
            block = (f"📖 <b>Explanation — {qid}</b>\n"
                     f"✅ Correct answer: <b>{letters[ci]}</b>\n\n{exp}")
            if ev:
                block += f"\n\n🔎 <b>Evidence:</b>\n<i>{ev}</i>"
            if len(block) > 3900:
                block = block[:3900] + "…"
            # Send explanation as a NEW message so the question stays visible above.
            send_text(chat_id, block,
                      reply_markup={"inline_keyboard": [[{"text": "▶️ Next question now", "callback_data": f"next|{qid}"}]]})
        tg("answerCallbackQuery", callback_query_id=cb["id"])
    elif kind == "next":
        if cur and qid == cur_qid:
            advance(when=time.time() + 2)
            tg("answerCallbackQuery", callback_query_id=cb["id"], text="Next question coming…")
        else:
            QS["next_due"] = min(QS.get("next_due", 0), time.time() + 2)
            save_state()
            tg("answerCallbackQuery", callback_query_id=cb["id"], text="Next question coming…")

def find_by_qid(qid):
    L = qid[0]
    try:
        idx = int(qid[1:]) - 1
    except Exception:
        return None
    if L in DATA and 0 <= idx < len(DATA[L]):
        return DATA[L][idx]
    return None

def handle(update):
    msg = update.get("message") or {}
    text = (msg.get("text") or "").strip()
    chat = msg.get("chat") or {}
    chat_id, user = chat.get("id"), msg.get("from") or {}
    if chat_id is None:
        return
    if text.startswith("/quiz"):
        if chat_id != OWNER_CHAT:
            send_text(chat_id, "📚 Quiz mode is in private beta — coming soon for everyone!")
            return
        arg = text[5:].strip().lower()
        if arg == "stop":
            QS["active"] = False
            save_state()
            send_text(chat_id, "⏸ Quiz paused. Send /quiz to resume.")
        elif arg == "status":
            cur = current_q()
            pos = f"Set {QS['set']}, next Q {QS['index'] + 1}" if cur else "bank complete"
            send_text(chat_id, f"📊 <b>Quiz status</b>\nPosition: {pos}\nToday: {QS['today_sent']}/{DAILY_LIMIT}\n"
                               f"Total answered: {QS['total_done']}\nActive: {'✅' if QS['active'] else '⏸'}")
        else:
            QS["active"] = True
            if QS.get("pending_qid") is None:
                QS["next_due"] = 0
            save_state()
            send_text(chat_id, "▶️ Quiz resumed/started — next question coming right up!")
            quiz_tick()
        return
    cmd = text.split()[0].split("@")[0].lower() if text.startswith("/") else None
    if cmd == "/start":
        send_text(chat_id, WELCOME)
    elif cmd == "/help":
        send_text(chat_id, HELP)
    elif cmd == "/about":
        send_text(chat_id, ABOUT)
    elif cmd == "/reset":
        MEM.pop(chat_id, None)
        send_text(chat_id, "🧹 Chat memory cleared. Fresh start!")
    elif text:
        tg("sendChatAction", chat_id=chat_id, action="typing")
        send_text(chat_id, groq_reply(chat_id, text))

# ---------------- main ----------------
def main():
    global QS
    me = tg("getMe")
    print("Bot running as", me.get("result", {}).get("username"))
    load_data()
    QS = gh_get_state() or default_state()
    print("quiz state:", {k: QS.get(k) for k in ("set", "index", "day", "today_sent", "active")})
    offset = None
    conflicts = 0
    last_tick = 0
    while True:
        try:
            if time.time() - last_tick > 20:
                quiz_tick()
                last_tick = time.time()
            params = {"timeout": 25, "allowed_updates": ["message", "callback_query"]}
            if offset:
                params["offset"] = offset
            data = requests.post(f"{TG}/getUpdates", json=params, timeout=40).json()
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
                    if "callback_query" in up:
                        handle_callback(up["callback_query"])
                    else:
                        handle(up)
                except Exception as e:
                    print("handle error:", e)
        except Exception as e:
            print("poll error:", e)
            time.sleep(3)

if __name__ == "__main__":
    main()
