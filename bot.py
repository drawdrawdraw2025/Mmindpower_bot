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
    "Commands: /quiz /quiz_pause /quiz_resume /quiz_status /quiz_reset /help"
)
HELP = (
    "❓ <b>Commands</b>\n\n"
    "📚 <b>Quiz</b>\n"
    "/quiz — start/resume daily quiz\n"
    "/quiz_pause — pause the quiz\n"
    "/quiz_resume — resume the quiz\n"
    "/quiz_status — your progress\n"
    "/quiz_reset — restart from any day (picker)\n\n"
    "🤖 <b>Bot</b>\n"
    "/reset — clear AI chat memory\n"
    "/help — this help\n"
    "/about — about this bot\n\n"
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
USERS = {}        # chat_id(str) -> per-user quiz state dict
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
        return {}
    try:
        r = requests.get(f"https://api.github.com/repos/{REPO}/contents/quiz_state.json",
                         headers={"Authorization": f"Bearer {GH_TOKEN}"}, timeout=30)
        if r.status_code == 404:
            return {}
        d = r.json()
        STATE_SHA = d["sha"]
        data = json.loads(base64.b64decode(d["content"]))
        if isinstance(data, dict) and "users" in data:
            return {str(k): v for k, v in data["users"].items()}
        if isinstance(data, dict) and "set" in data:   # legacy flat state
            return {str(OWNER_CHAT): data}
        return {}
    except Exception as e:
        print("state load err:", e)
        return {}

def u_state(chat_id):
    k = str(chat_id)
    if k not in USERS:
        USERS[k] = default_state()
    return USERS[k]

def gh_save_state():
    global STATE_SHA
    if not (GH_TOKEN and REPO):
        return
    try:
        body = {"message": "quiz state update",
                "content": base64.b64encode(json.dumps({"users": USERS}).encode()).decode(),
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

def current_q(us):
    if not DATA:
        return None
    L = us["set"]
    while L and L not in DATA:
        L = next_set(L)
    if not L or L not in DATA:
        return None
    if us["index"] >= len(DATA[L]):
        return None
    return L, us["index"], DATA[L][us["index"]]

def next_set(L):
    order = sorted(DATA.keys())
    i = order.index(L) if L in order else -1
    return order[i + 1] if 0 <= i < len(order) - 1 else None

# ---------------- Quiz messages ----------------
def q_text_block(set_letter, index, q, us):
    mr = q.get("q_marathi", "")
    en = q.get("q_english", "")
    opts = q.get("options", [])
    letters = ["A", "B", "C", "D"]
    opt_lines = "\n".join(f"<b>{letters[i]})</b> {opts[i]}" for i in range(min(4, len(opts))))
    head = (f"📚 <b>Daily Quiz — Set {set_letter}</b>  "
            f"(Q {index + 1}/{len(DATA[set_letter])} • today {us['today_sent']}/{DAILY_LIMIT})\n\n")
    return head, mr, en, opt_lines

def q_body(set_letter, index, q, us, with_english=True, limit=3950):
    """Full question text (question + options), optionally with English, kept under limit."""
    head, mr, en, opt_lines = q_text_block(set_letter, index, q, us)
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
        {"text": "🅳 D", "callback_data": f"ans|{qid}|3"}], [
        {"text": "📖 Reveal answer & explanation", "callback_data": f"rev|{qid}"}]]}

def kb_show(qid):
    return {"inline_keyboard": [
        [{"text": "📖 Show Explanation", "callback_data": f"exp|{qid}"}],
        [{"text": "▶️ Next question now", "callback_data": f"next|{qid}"}]]}

def kb_hide_inline(qid):
    return {"inline_keyboard": [
        [{"text": "🙈 Hide Explanation", "callback_data": f"hexp|{qid}"}],
        [{"text": "▶️ Next question now", "callback_data": f"next|{qid}"}]]}

def get_q(qid):
    L = qid[0]
    try:
        idx = int(qid[1:]) - 1
    except Exception:
        return None
    if L in DATA and 0 <= idx < len(DATA[L]):
        return L, idx, DATA[L][idx]
    return None

def fit_body(L, idx, q, us, tail):
    body = q_body(L, idx, q, us)
    if len(body) + len(tail) <= 4000:
        return body
    body = q_body(L, idx, q, us, with_english=False)
    if len(body) + len(tail) <= 4000:
        return body
    return q_body(L, idx, q, us, with_english=False, limit=max(500, 4000 - len(tail) - 10))

def exp_block(qid, q):
    ci = q.get("correct_index", 0)
    letters = "ABCD"
    exp = q.get("explanation_marathi", "")
    ev = q.get("evidence", "")
    b = (f"📖 <b>Explanation — {qid}</b>\n"
         f"✅ Correct answer: <b>{letters[ci]}</b>\n\n{exp}")
    if ev:
        b += f"\n\n🔎 <b>Evidence:</b>\n<i>{ev}</i>"
    return b[:3950]

def send_question(chat_id):
    us = u_state(chat_id)
    cur = current_q(us)
    if not cur:
        send_text(chat_id, "🎉 <b>All available quiz sets are complete!</b> More sets coming soon.")
        us["active"] = False
        save_state()
        return False
    L, idx, q = cur
    qid = qid_of(L, idx)
    us["today_sent"] += 1
    us["total_done"] += 1
    head, mr, en, opt_lines = q_text_block(L, idx, q, us)
    body = f"{head}🇮🇳 {mr}\n\n<b>Options:</b>\n{opt_lines}"
    if len(body) + len(en) < 3900:
        body += f"\n\n🇬🇧 <i>{en}</i>"
        en_sent_inside = True
    else:
        en_sent_inside = False
    res = send_text(chat_id, body, reply_markup=kb_answers(qid))
    msg_id = (res.get("result") or {}).get("message_id")
    if not en_sent_inside and en:
        send_text(chat_id, f"🇬🇧 <i>{en}</i>")
    us["pending_qid"] = qid
    us["pending_msg"] = msg_id
    us["next_due"] = time.time() + IDLE_NEXT_SECS
    save_state()
    print(f"sent {qid} to {chat_id}")
    return True

def advance(chat_id, when=None):
    """Move pointer to next question; cross into next set if needed."""
    us = u_state(chat_id)
    L = us["set"]
    if L in DATA and us["index"] + 1 < len(DATA[L]):
        us["index"] += 1
    else:
        nxt = next_set(L)
        if nxt:
            us["set"] = nxt
            us["index"] = 0
        else:
            us["active"] = False
    us["next_due"] = when if when else time.time()
    us["pending_qid"] = None
    us["pending_msg"] = None
    save_state()

def day_plan():
    """List of quiz days: (day_no, set_letter, start_idx, end_idx, date_str)."""
    plan = []
    day = 1
    base = datetime.datetime.now(IST).replace(hour=0, minute=0, second=0, microsecond=0)
    for L in sorted(DATA.keys()):
        n = len(DATA[L])
        start = 0
        while start < n:
            end = min(start + DAILY_LIMIT, n)
            d = base + datetime.timedelta(days=day - 1)
            plan.append((day, L, start, end, d.strftime("%d %b")))
            day += 1
            start = end
    return plan

def kb_daypicker():
    rows = []
    for day, L, start, end, ds in day_plan():
        label = f"📅 Day {day} ({ds}) — Set {L}, Q{start + 1}-{end}"
        rows.append([{"text": label, "callback_data": f"pickday|{L}|{start}"}])
    rows.append([{"text": "❌ Cancel", "callback_data": "pickcancel"}])
    return {"inline_keyboard": rows}

def tick_user(chat_id, now):
    us = USERS[str(chat_id)]
    if not us.get("active"):
        return
    today = now.strftime("%Y-%m-%d")
    if today != us["day"]:
        us["day"] = today
        us["today_sent"] = 0
        save_state()
    if us["today_sent"] >= DAILY_LIMIT:
        return
    if not (SEND_HOUR_START <= now.hour < SEND_HOUR_END):
        return
    if time.time() < us.get("next_due", 0):
        return
    if us.get("pending_qid"):
        # User didn't answer in time: move on silently, no auto-reveal.
        advance(chat_id, when=time.time() + 30)
        return
    send_question(chat_id)

def quiz_tick():
    if not DATA or not USERS:
        return
    now = datetime.datetime.now(IST)
    for k in list(USERS.keys()):
        try:
            tick_user(int(k), now)
        except Exception as e:
            print("tick err", k, e)

def handle_callback(cb):
    data = cb.get("data", "")
    parts = data.split("|")
    kind = parts[0] if parts else ""
    chat_id = cb["message"]["chat"]["id"]
    msg_id = cb["message"]["message_id"]

    def ack(text=""):
        tg("answerCallbackQuery", callback_query_id=cb["id"], text=text)

    us = u_state(chat_id)
    cur = current_q(us)
    cur_qid = qid_of(cur[0], cur[1]) if cur else None

    if kind == "ans":
        qid = parts[1]
        g = get_q(qid)
        if not g:
            ack("Question unavailable.")
            return
        L, idx, q = g
        chosen = int(parts[2])
        ci = q.get("correct_index", 0)
        letters = "ABCD"
        verdict = ("✅ <b>Correct!</b>" if chosen == ci else
                   f"❌ You chose <b>{letters[chosen]}</b>. Correct answer: <b>{letters[ci]}</b>")
        tail = f"\n\n{verdict}"
        body = fit_body(L, idx, q, us, tail)
        edit_text(chat_id, msg_id, body + tail, reply_markup=kb_show(qid))
        ack("Correct!" if chosen == ci else f"Correct answer: {letters[ci]}")
        if qid == cur_qid:
            advance(chat_id, when=time.time() + ANSWERED_NEXT_SECS)
            us["_answered_qid"] = qid
        # old/skipped questions: no state change — buttons keep working

    elif kind == "rev":
        qid = parts[1]
        g = get_q(qid)
        if not g:
            ack("Question unavailable.")
            return
        L, idx, q = g
        ci = q.get("correct_index", 0)
        tail = f"\n\n🔓 <b>Answer revealed — correct answer: {'ABCD'[ci]}</b>"
        body = fit_body(L, idx, q, us, tail)
        edit_text(chat_id, msg_id, body + tail, reply_markup=kb_show(qid))
        ack(f"Correct answer: {'ABCD'[ci]}")
        if qid == cur_qid:
            advance(chat_id, when=time.time() + ANSWERED_NEXT_SECS)
            us["_answered_qid"] = qid

    elif kind == "exp":
        qid = parts[1]
        g = get_q(qid)
        if not g:
            ack("Question unavailable.")
            return
        L, idx, q = g
        block = exp_block(qid, q)
        ans_line = f"\n\n✅ Correct answer: <b>{'ABCD'[q.get('correct_index', 0)]}</b>"
        tail = f"{ans_line}\n\n{block}"
        body = fit_body(L, idx, q, us, tail)
        if len(body) + len(tail) <= 4000:
            # toggle inline: show
            edit_text(chat_id, msg_id, body + tail, reply_markup=kb_hide_inline(qid))
        else:
            # explanation as separate message with its own hide button
            exp_kb = {"inline_keyboard": [[{"text": "🙈 Hide Explanation",
                                            "callback_data": f"hx|{msg_id}|{qid}"}]]}
            r = send_text(chat_id, block, reply_markup=exp_kb)
            exp_id = (r.get("result") or {}).get("message_id")
            if exp_id:
                q_kb = {"inline_keyboard": [
                    [{"text": "🙈 Hide Explanation",
                      "callback_data": f"hxd|{exp_id}|{msg_id}|{qid}"}],
                    [{"text": "▶️ Next question now",
                      "callback_data": f"next|{qid}"}]]}
                tg("editMessageReplyMarkup", chat_id=chat_id, message_id=msg_id,
                   reply_markup=q_kb)
        ack()

    elif kind == "hexp":
        qid = parts[1]
        g = get_q(qid)
        if g:
            L, idx, q = g
            tail = f"\n\n✅ Correct answer: <b>{'ABCD'[q.get('correct_index', 0)]}</b>"
            body = fit_body(L, idx, q, us, tail)
            edit_text(chat_id, msg_id, body + tail, reply_markup=kb_show(qid))
        ack("Hidden.")

    elif kind == "hx":
        # hide button on the separate explanation message itself
        try:
            q_msg_id = int(parts[1])
        except Exception:
            q_msg_id = None
        qid = parts[2] if len(parts) > 2 else ""
        tg("deleteMessage", chat_id=chat_id, message_id=msg_id)
        if q_msg_id and qid:
            tg("editMessageReplyMarkup", chat_id=chat_id, message_id=q_msg_id,
               reply_markup=kb_show(qid))
        ack("Hidden.")

    elif kind == "hxd":
        # hide button on the question message while explanation is separate
        try:
            exp_id = int(parts[1])
            q_msg_id = int(parts[2])
        except Exception:
            ack()
            return
        qid = parts[3] if len(parts) > 3 else ""
        tg("deleteMessage", chat_id=chat_id, message_id=exp_id)
        if q_msg_id and qid:
            tg("editMessageReplyMarkup", chat_id=chat_id, message_id=q_msg_id,
               reply_markup=kb_show(qid))
        ack("Hidden.")

    elif kind == "pickday":
        L = parts[1]
        try:
            start = int(parts[2])
        except Exception:
            ack()
            return
        if L not in DATA or not (0 <= start < len(DATA[L])):
            ack("That quiz is not available.")
            return
        today = datetime.datetime.now(IST).strftime("%Y-%m-%d")
        day_no = None
        for d, LL, st, en, ds in day_plan():
            if LL == L and st == start:
                day_no = d
                break
        us.update({"set": L, "index": start, "day": today, "today_sent": 0,
                   "next_due": 0, "pending_qid": None, "pending_msg": None,
                   "active": True})
        save_state()
        edit_text(chat_id, msg_id,
                  f"✅ <b>Restarted: Day {day_no} — Set {L}</b> (from Q{start + 1})\n"
                  f"First question arriving now! 🚀")
        ack("Reset done!")
        quiz_tick()

    elif kind == "pickcancel":
        edit_text(chat_id, msg_id, "❌ Reset cancelled — your progress is unchanged.")
        ack()

    elif kind == "next":
        qid = parts[1] if len(parts) > 1 else ""
        if cur and qid == cur_qid:
            advance(chat_id, when=time.time() + 2)
        else:
            us["next_due"] = min(us.get("next_due", 0), time.time() + 2)
            save_state()
        ack("Next question coming…")


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
    token0 = text.split()[0].split("@")[0].lower() if text.startswith("/") else ""
    if token0 in ("/quiz", "/quiz_pause", "/quiz_resume", "/quiz_reset", "/quiz_status"):
        us = u_state(chat_id)
        if token0 == "/quiz_pause":
            action = "pause"
        elif token0 == "/quiz_resume":
            action = "start"
        elif token0 == "/quiz_reset":
            action = "reset"
        elif token0 == "/quiz_status":
            action = "status"
        else:
            arg = text[len(token0):].strip().lower()
            if arg in ("stop", "pause"):
                action = "pause"
            elif arg == "reset":
                action = "reset"
            elif arg == "status":
                action = "status"
            else:
                action = "start"
        if action == "reset":
            txt = ("🔄 <b>Quiz Reset</b>\n\nPick any day's quiz to restart from — "
                   "progress moves to that day's first question and its 90 "
                   "questions will be delivered today. 📅")
            send_text(chat_id, txt, reply_markup=kb_daypicker())
        elif action == "pause":
            us["active"] = False
            save_state()
            send_text(chat_id, "⏸ Quiz paused. Send /quiz_resume to continue.")
        elif action == "status":
            cur = current_q(us)
            pos = f"Set {us['set']}, next Q {us['index'] + 1}" if cur else "bank complete"
            send_text(chat_id, f"📊 <b>Quiz status</b>\nPosition: {pos}\nToday: {us['today_sent']}/{DAILY_LIMIT}\n"
                               f"Total answered: {us['total_done']}\nActive: {'✅' if us['active'] else '⏸'}")
        else:
            us["active"] = True
            if us.get("pending_qid") is None:
                us["next_due"] = 0
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
    global USERS
    me = tg("getMe")
    print("Bot running as", me.get("result", {}).get("username"))
    tg("setMyCommands", commands=[
        {"command": "start", "description": "👋 Welcome & intro"},
        {"command": "quiz", "description": "📚 Start / resume daily quiz"},
        {"command": "quiz_pause", "description": "⏸ Pause the quiz"},
        {"command": "quiz_resume", "description": "▶️ Resume the quiz"},
        {"command": "quiz_status", "description": "📊 Your quiz progress"},
        {"command": "quiz_reset", "description": "🔄 Restart from any day"},
        {"command": "reset", "description": "🧹 Clear AI chat memory"},
        {"command": "help", "description": "❓ Help"},
        {"command": "about", "description": "🤖 About this bot"},
    ])
    load_data()
    USERS = gh_get_state() or {}
    print("quiz users:", len(USERS))
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
