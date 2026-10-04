#!/usr/bin/env python3
"""Mmindpower_bot — Telegram bot: AI chat + Daily Quiz (90 Qs/day, clickable answers).
Zero-dependency (requests only), long-polling. Run: python3 bot.py
Env: TG_TOKEN, GROQ_KEY, GH_TOKEN + REPO (for quiz state persistence on GitHub).
"""
import os, json, time, base64, datetime, requests
import re, io, html

TOKEN = os.environ["TG_TOKEN"]
GROQ_KEY = os.environ["GROQ_KEY"]
GH_TOKEN = os.environ.get("GH_TOKEN", "")
REPO = os.environ.get("REPO", "")
TG = f"https://api.telegram.org/bot{TOKEN}"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "openai/gpt-oss-120b"

OWNER_CHAT = 7102918717          # Balu (@Mmindpower1)
DAILY_LIMIT = 90                 # questions per day
AI_DAILY_LIMIT = 90
AI_WARN_AT = 75
SEND_HOUR_START, SEND_HOUR_END = 0, 24  # 24x7 delivery
IDLE_NEXT_SECS = 10 * 60         # next question if user doesn't answer
ANSWERED_NEXT_SECS = 5           # next question after user answers (near-instant)
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))

WELCOME = (
    "🚀 <b>Welcome to Mmindpower Bot!</b>\n"
    "📣 <b>Join our Channel:</b> @mmindpower_1 — daily quiz & answers 🔔\n"
    "📺 <b>Subscribe on YouTube:</b> youtube.com/@mmindpower 🔔\n\n"
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
    "/donate — ☕ support Mmindpower (optional, ₹5)\n"
    "/app — 📚 practice app (all sets, any time)\n"
    "/help — this help\n"
    "/about — about this bot\n\n"
    "Or simply send any text and the AI will reply. 💬"
)
ABOUT = ("🤖 <b>About Mmindpower Bot</b>\n\nAI assistant + Daily Quiz engine.\n"
         "Quiz bank: Talathi MPSC 2026 sets.\n\nPowered by <b>Mmindpower</b> 💖")
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
    res = tg("sendMessage", **p)
    if not res.get("ok"):
        p = dict(chat_id=chat_id, text=re.sub(r"<[^>]+>", "", text),
                 link_preview_options={"is_disabled": True})
        if reply_markup:
            p["reply_markup"] = reply_markup
        res = tg("sendMessage", **p)
    return res

def edit_text(chat_id, msg_id, text, reply_markup=None):
    p = dict(chat_id=chat_id, message_id=msg_id, text=text, parse_mode="HTML",
             link_preview_options={"is_disabled": True})
    if reply_markup:
        p["reply_markup"] = reply_markup
    res = tg("editMessageText", **p)
    if not res.get("ok"):
        p = dict(chat_id=chat_id, message_id=msg_id, text=re.sub(r"<[^>]+>", "", text),
                 link_preview_options={"is_disabled": True})
        if reply_markup:
            p["reply_markup"] = reply_markup
        res2 = tg("editMessageText", **p)
        if res2.get("ok"):
            return res2
        return send_text(chat_id, text, reply_markup)
    return res

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
            "active": True, "total_done": 0,
            "done": {}, "stats": {}, "first_seen": 0, "last_seen": 0}

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

LAST_STATE_SAVE = {"t": 0.0}

def save_state(force=False):
    now = time.time()
    if not force and now - LAST_STATE_SAVE["t"] < 120:
        return
    LAST_STATE_SAVE["t"] = now
    gh_save_state()

DONATE_UPI = "mmindpower.contact@oksbi"
DONATE_URL = "https://drawdrawdraw2025.github.io/pay/"
APP_URL = "https://drawdrawdraw2025.github.io/app/"
# Cache-busted variants — Telegram's webview hard-caches per-URL; bump ?v= to force fresh load
APP_URL_V = APP_URL + "?v=web9"
DONATE_URL_V = DONATE_URL + "?v=web9"
APP_MENU_DONE = set()
CHANNEL_ID = "@mmindpower_1"

def donate_qr_png():
    try:
        import qrcode
        qr = qrcode.QRCode(box_size=12, border=4)
        qr.add_data(DONATE_URL)
        qr.make(fit=True)
        img = qr.make_image(fill_color=(16, 42, 86), back_color="white")
        bio = io.BytesIO()
        img.save(bio, format="PNG")
        bio.seek(0)
        return bio.getvalue()
    except Exception as e:
        print("qr error:", e)
        return None

def send_donate(chat_id):
    cap = ("☕ <b>Small Support — Mmindpower Bot</b>\n\n"
           "If today's quiz helped you even a little, support us with <b>₹5</b> 💖\n"
           "100% optional — Mmindpower stays <b>free forever</b> 🎓\n\n"
           "📷 Scan this QR with your camera\n"
           f"🆔 <code>{DONATE_UPI}</code> (tap to copy)\n\n"
           "🙏 धन्यवाद — तुमचं प्रेम आमचं इंधन! 💪")
    kb = {"inline_keyboard": [[{"text": "💸 Tap to Support ₹5 (UPI)", "web_app": {"url": DONATE_URL_V}}]]}
    png = donate_qr_png()
    if png:
        tg_photo(chat_id, png, caption=cap, reply_markup=kb)
    else:
        send_text(chat_id, cap, reply_markup=kb)

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
# ---------------- Data-question rendering: Devanagari text + English PNG tables ----------------
PIL_OK = False
try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_OK = True
except Exception:
    pass

DEV_RE = re.compile(r"[\u0900-\u097F]")
MARK_RE = re.compile(r"\(((?:[A-H])|(?:[a-e])|(?:[\u0905-\u0939])|(?:i{1,3}|iv|v)|(?:\d{1,2}))\)\s*")
ROMAN_RE = re.compile(r"\((i{1,3}|iv|v)\)\s*", re.I)
NUMPAREN_RE = re.compile(r"\(\d{1,2}\)\s*")

def has_dev(s):
    return bool(DEV_RE.search(s or ""))

def intro_lines(text):
    keep = []
    for l in (text or "").split("\n"):
        if l.count("|") < 2:
            keep.append(l)
        else:
            head = l.split("|", 1)[0].strip()
            if head:
                keep.append(head)
    return "\n".join(keep).strip()

def parse_pipe_rows(text):
    rows = []
    for line in (text or "").split("\n"):
        if line.count("|") >= 2:
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if any(cells):
                rows.append(cells)
    if len(rows) >= 2:
        return rows
    # one-line table: intro | h1 | h2 | | c1 | c2 | | ...
    for line in (text or "").split("\n"):
        if line.count("|") >= 4:
            cells = [c.strip() for c in line.split("|", 1)[1].strip().strip("|").split("|")]
            rows, cur = [], []
            for c in cells:
                if c == "":
                    if cur:
                        rows.append(cur)
                        cur = []
                else:
                    cur.append(c)
            if cur:
                rows.append(cur)
            if len(rows) >= 2 and all(len(r) == len(rows[0]) for r in rows):
                return rows
    return []

def mono_table(rows):
    cols = max(len(r) for r in rows)
    rows = [r + [""] * (cols - len(r)) for r in rows]
    widths = [max(len(r[i]) for r in rows) for i in range(cols)]
    def hline(l, m, rr):
        return l + m.join("─" * (w + 2) for w in widths) + rr
    def rowl(r):
        return "│ " + " │ ".join(r[i].ljust(widths[i]) for i in range(cols)) + " │"
    out = [hline("┌", "┬", "┐")]
    out.append(rowl(rows[0]))
    out.append(hline("├", "┼", "┤"))
    for r in rows[1:]:
        out.append(rowl(r))
    out.append(hline("└", "┴", "┘"))
    return "\n".join(out)

def _is_num_marker(mm):
    return bool(ROMAN_RE.match(mm.group(0)) or NUMPAREN_RE.match(mm.group(0)))

def extract_pairs(text):
    """(A) x (B) y ... (1)/(i) p (2)/(ii) q -> (intro, listA, listB)."""
    t = (text or "").strip()
    if not t:
        return None
    m = list(MARK_RE.finditer(t))
    if len(m) < 4:
        return None
    first_num = None
    for k, mm in enumerate(m):
        if _is_num_marker(mm):
            first_num = k
            break
    if first_num is None or first_num < 2 or len(m) - first_num < 2:
        return None
    intro = t[:m[0].start()].rstrip(" :-–—")
    listA, listB = [], []
    for k, mm in enumerate(m):
        end = m[k + 1].start() if k + 1 < len(m) else len(t)
        item = t[mm.end():end].strip().rstrip("—–-:;|,").strip()
        if k == first_num - 1:
            dpos = item.find("—")
            col = item.find(" :")
            cut = min([p for p in (dpos, col) if p != -1], default=-1)
            if cut != -1:
                item = item[:cut].strip().rstrip("—–-:;|,").strip()
        (listB if k >= first_num else listA).append(f"({mm.group(1)}) {item}")
    if len(listA) < 2 or len(listB) < 2:
        return None
    return intro, listA, listB

def verticalize_pairs(text):
    ext = extract_pairs(text)
    if not ext:
        return None
    intro, listA, listB = ext
    NL = "\n"
    return (intro + NL + NL + "📋 <b>List I / यादी I</b>" + NL + NL.join(listA)
            + NL + NL + "📋 <b>List II / यादी II</b>" + NL + NL.join(listB))

def _font(sz, bold=False):
    cand = ["/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"] if bold else \
           ["/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    for p in cand:
        try:
            return ImageFont.truetype(p, sz)
        except Exception:
            continue
    return ImageFont.load_default()

def table_png(rows):
    """Exam-paper PNG; header row styled navy. If rows[0] is all-blank -> headerless mode (first col = bold navy titles)."""
    if not PIL_OK:
        return None
    headerless = bool(rows) and all(not str(c).strip() for c in rows[0])
    if headerless:
        rows = rows[1:]
    if not rows:
        return None
    rows = [[html.unescape(str(c)) for c in r] for r in rows]
    cols = max(len(r) for r in rows)
    rows = [r + [""] * (cols - len(r)) for r in rows]
    f_reg, f_bold = _font(26), _font(26, True)
    PADX, PADY, LINE_H = 18, 12, 32
    COL_MIN, COL_MAX = 150, 460
    def cell_font(ri, c):
        if headerless:
            return f_bold if c == 0 else f_reg
        return f_bold if ri == 0 else f_reg
    def cell_color(ri, c):
        if headerless:
            return (31, 59, 115) if c == 0 else (25, 32, 56)
        return "white" if ri == 0 else (25, 32, 56)
    tmp = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    def tw(t, f):
        try:
            return f.getbbox(t)[2]
        except Exception:
            return f.getsize(t)[0]
    widths = []
    for c in range(cols):
        natural = max(tw(r[c], cell_font(ri, c)) for ri, r in enumerate(rows))
        longest_word = max((tw(w, cell_font(ri, c)) for ri, r in enumerate(rows) for w in r[c].split()), default=60)
        w = min(natural, COL_MAX)
        w = max(w, longest_word + 12, COL_MIN)
        widths.append(min(w, COL_MAX) + PADX * 2)
    def wrap(t, f, wmax):
        lines, cur = [], ""
        for wd in t.split(" "):
            trial = (cur + " " + wd).strip()
            if not cur or tw(trial, f) <= wmax:
                cur = trial
            else:
                lines.append(cur)
                cur = wd
        if cur:
            lines.append(cur)
        return lines or [""]
    wrapped, row_hs = [], []
    for ri, r in enumerate(rows):
        wr = [wrap(c0, cell_font(ri, c), widths[c] - PADX * 2) for c, c0 in enumerate(r)]
        wrapped.append(wr)
        row_hs.append(max(len(x) for x in wr) * LINE_H + PADY * 2)
    W, H = sum(widths) + 3, sum(row_hs) + 3
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    head_bg, alt_bg, grid_c = (31, 59, 115), (240, 244, 255), (205, 213, 235)
    y = 1
    for ri, wr in enumerate(wrapped):
        if headerless:
            bg = alt_bg if ri % 2 == 1 else (255, 255, 255)
        else:
            bg = head_bg if ri == 0 else (alt_bg if ri % 2 == 0 else (255, 255, 255))
        d.rectangle([1, y, W - 2, y + row_hs[ri]], fill=bg)
        x = 1
        for c, lines in enumerate(wr):
            yy = y + PADY
            for ln in lines:
                d.text((x + PADX, yy), ln, font=cell_font(ri, c), fill=cell_color(ri, c))
                yy += LINE_H
            x += widths[c]
        y += row_hs[ri]
    x = 1
    for w in widths[:-1]:
        x += w
        d.line([(x, 1), (x, H - 1)], fill=grid_c, width=1)
    y = 1
    for hgt in row_hs:
        y += hgt
        d.line([(1, y), (W - 1, y)], fill=grid_c, width=1)
    d.rectangle([0, 0, W - 1, H - 1], outline=head_bg, width=3)
    bio = io.BytesIO()
    img.save(bio, "PNG")
    bio.seek(0)
    return bio.getvalue()

def row_cards(rows):
    """Devanagari/short-latin pipe tables -> phone-friendly 'A -> value' row cards."""
    if len(rows) < 3:
        return None
    head, body = rows[0], rows[1:]
    def marked(c):
        return bool(re.match(r"^([A-E]|[\u0905-\u0921])[\.\)]\s*", (c or "").strip()))
    if not all(marked(r[0]) for r in body):
        return None
    out = ["📊 " + " → ".join(head)] if len(head) >= 2 and not marked(head[0]) else ["📊"]
    for r in body:
        first = r[0].strip()
        rest = [x.strip() for x in r[1:] if x.strip()]
        if not rest:
            continue
        out.append(f"{first} → " + " • ".join(rest))
    return "\n".join(out)

def extract_dot_pairs(text):
    """A. x, B. y ; 1. p, 2. q dot-style pairs -> (intro, listA, listB)."""
    t = (text or "").strip()
    if not any(k in t for k in ("जोड्या", "जोडी", "लावा", "Match")):
        return None
    lm = list(re.finditer(r"(?:^|[,; ]\s*)([A-E])\.(?!\d)\s*", t))
    dm = list(re.finditer(r"(?:^|[,; ]\s*)([1-9])\.(?!\d)\s*", t))
    if len(lm) < 2 or len(dm) < 2:
        return None
    marks = [m for _, m in sorted({m.start(): m for m in (lm + dm)}.items())]
    if not any(m.group(1).isdigit() for m in marks):
        return None
    first = marks[0]
    intro = t[:first.start()].rstrip(",").replace("अ गट:", "").replace('"', "").strip().rstrip(":;–—- ")
    listA, listB = [], []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(t)
        item = t[m.end():end].strip().rstrip(";").replace("ब गट:", "").strip().rstrip(",;–—- ")
        (listB if m.group(1).isdigit() else listA).append(f"{m.group(1)}. {item}")
    if len(listA) < 2 or len(listB) < 2:
        return None
    return intro, listA, listB

def verticalize_dots(text):
    ext = extract_dot_pairs(text)
    if not ext:
        return None
    intro, listA, listB = ext
    NL = "\n"
    return (intro + NL + NL + "📋 <b>गट A / List A</b>" + NL + NL.join(listA)
            + NL + NL + "📋 <b>गट B / List B</b>" + NL + NL.join(listB))

DASH_SPLIT = re.compile(r"\s*[—–]\s*|\s+-\s+")

def parse_dash_rows(text):
    """Dash tables: 'तक्ता : h1 — h2 — h3. (P) a — b — c (Q) d — e — f'."""
    t = (text or "")
    ms = list(re.finditer(r"\((?:[A-Z]|[1-9][0-9]?|[ivx]{1,3})\)\s*", t))
    if len(ms) < 2 or not DASH_SPLIT.search(t):
        return None
    rows = []
    for i, m in enumerate(ms):
        seg = t[m.end(): ms[i + 1].start() if i + 1 < len(ms) else len(t)]
        if not DASH_SPLIT.search(seg):
            continue
        cells = [c.strip(" .;:,") for c in DASH_SPLIT.split(seg) if c.strip(" .;:,")]
        if i == len(ms) - 1 and cells:
            tail = cells[-1]
            pos = 0
            while True:
                cut = tail.find(". ", pos)
                if cut == -1:
                    break
                if len(tail[cut + 2:].split()) >= 2:
                    cells[-1] = tail[:cut]
                    break
                pos = cut + 2
        if len(cells) >= 2:
            rows.append([m.group(0).strip() + " " + cells[0]] + cells[1:])
    if len(rows) < 2:
        return None
    mlen = max(len(r) for r in rows)
    rows = [r + [""] * (mlen - len(r)) for r in rows]
    intro_all = t[:ms[0].start()].strip()
    header, intro = None, intro_all
    if ":" in intro_all and DASH_SPLIT.search(intro_all.rsplit(":", 1)[1]):
        hseg = intro_all.rsplit(":", 1)[1]
        header = [h.strip(" .;") for h in DASH_SPLIT.split(hseg) if h.strip(" .;")]
        intro = intro_all.rsplit(":", 1)[0].strip()
        if len(header) < mlen:
            header = header + [""] * (mlen - len(header))
        elif len(header) != mlen:
            header, intro = None, intro_all
    return {"intro": intro, "header": header, "rows": rows}

def dash_cards(d):
    parts = []
    intro = (d.get("intro") or "").strip()
    if intro:
        parts.append(intro.rstrip(":") + ":")
    hdr = d.get("header")
    if hdr:
        parts.append("📊 " + " → ".join(hdr))
    for r in d["rows"]:
        parts.append(r[0] + " → " + " • ".join(r[1:]))
    return "\n".join(parts)

def section_cards(rows):
    """3+ col tables with long cells -> per-row section cards (Devanagari-safe)."""
    if len(rows) < 3:
        return None
    head, body = rows[0], rows[1:]
    out = ["📊 " + " → ".join(head)] if len(head) >= 2 and str(head[0]).strip() else ["📊"]
    for r in body:
        if len(r) < 2 or not str(r[0]).strip():
            continue
        out.append("\n▫️ <b>" + str(r[0]).strip() + "</b>")
        for c, cell in enumerate(r[1:], start=1):
            if not str(cell).strip():
                continue
            lab = head[c] if c < len(head) and str(head[c]).strip() else f"Col {c + 1}"
            out.append(f"  • {lab}: {cell}")
    return "\n".join(out)

def _mostly_latin(cells, ratio):
    cells = list(cells)
    if not cells:
        return False
    latin = sum(1 for c in cells if not has_dev(str(c)))
    return latin >= max(1, len(cells)) * ratio

def prepare_data(mr, en):
    mr2, en2, png_rows = mr, en, None
    # ---------- Marathi side: text-native comfort ----------
    rows_mr = parse_pipe_rows(mr)
    if len(rows_mr) >= 2:
        intro = intro_lines(mr)
        cards = row_cards(rows_mr)
        longest = max((len(str(c)) for r in rows_mr[1:] for c in r), default=0)
        if cards and longest <= 30:
            mr2 = intro + "\n\n" + cards
        else:
            sec = section_cards(rows_mr)
            mr2 = intro + "\n\n" + (sec or "<pre>\n" + mono_table(rows_mr) + "\n</pre>")
    else:
        d0 = parse_dash_rows(mr)
        if d0:
            mr2 = dash_cards(d0)
        else:
            v = verticalize_pairs(mr) or verticalize_dots(mr)
            if v:
                mr2 = v
    # ---------- English side: PNG-chart comfort ----------
    rows_en = parse_pipe_rows(en)
    if len(rows_en) >= 2 and PIL_OK and _mostly_latin([c for r in rows_en for c in r], 0.6):
        png_rows = rows_en
        en2 = intro_lines(en) or "📊 table in image"
    elif len(rows_en) >= 2:
        intro = intro_lines(en)
        cards = row_cards(rows_en)
        en2 = intro + "\n\n" + (cards or "<pre>\n" + mono_table(rows_en) + "\n</pre>")
    else:
        d0 = parse_dash_rows(en)
        if d0 and PIL_OK and _mostly_latin((d0["header"] or []) + [c for r in d0["rows"] for c in r], 0.6):
            if d0.get("header"):
                png_rows = [d0["header"]] + d0["rows"]
            else:
                png_rows = [[""] * len(d0["rows"][0])] + d0["rows"]
            en2 = (d0.get("intro") or "").strip() or "📊 table in image"
        else:
            ext = extract_pairs(en) or extract_dot_pairs(en)
            if ext and PIL_OK:
                intro, listA, listB = ext
                if _mostly_latin(listA + listB, 0.7):
                    n = max(len(listA), len(listB))
                    png_rows = [["List A", "List B"]] + [[
                        listA[i] if i < len(listA) else "",
                        listB[i] if i < len(listB) else ""] for i in range(n)]
                    en2 = intro.strip() or "📊 chart in image"
            if png_rows is None:
                v = verticalize_pairs(en) or verticalize_dots(en)
                if v:
                    en2 = v
    return mr2, en2, png_rows

def tg_photo(chat_id, png_bytes, caption=None, reply_markup=None):
    data = {"chat_id": chat_id}
    if caption:
        data["caption"] = caption
        data["parse_mode"] = "HTML"
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup)
    try:
        r = requests.post(f"{TG}/sendPhoto", data=data,
                          files={"photo": ("table.png", png_bytes, "image/png")}, timeout=60)
        return r.json()
    except Exception as e:
        print("sendPhoto error:", e)
        return {}

def q_text_block(set_letter, index, q, us):
    mr = html.escape(q.get("q_marathi", "") or "", quote=False)
    en = html.escape(q.get("q_english", "") or "", quote=False)
    opts = [html.escape(str(o or ""), quote=False) for o in q.get("options", [])]
    letters = ["A", "B", "C", "D"]
    opt_lines = "\n".join(f"<b>{letters[i]})</b> {opts[i]}" for i in range(min(4, len(opts))))
    head = (f"📚 <b>Daily Quiz — Set {set_letter}</b>  "
            f"(Q {index + 1}/{len(DATA[set_letter])} • today {us['today_sent']}/{DAILY_LIMIT})\n\n")
    mr, en, png_rows = prepare_data(mr, en)
    return head, mr, en, opt_lines, png_rows

def q_body(set_letter, index, q, us, with_english=True, limit=3950):
    """Full question text (question + options), optionally with English, kept under limit."""
    head, mr, en, opt_lines, _ = q_text_block(set_letter, index, q, us)
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

def _safe_cut(txt, room):
    if len(txt) <= room:
        return txt
    cut = txt[:max(0, room - 1)]
    tail = cut[-4:]
    if "&" in tail and ";" not in tail.rsplit("&", 1)[1]:
        cut = cut[:cut.rfind("&")]
    return cut + "…"

def exp_block(qid, q):
    ci = q.get("correct_index", 0)
    letters = "ABCD"
    exp = html.escape(q.get("explanation_marathi", "") or "", quote=False)
    ev = html.escape(q.get("evidence", "") or "", quote=False)
    b = (f"📖 <b>Explanation — {qid}</b>\n"
         f"✅ Correct answer: <b>{letters[ci]}</b>\n\n{exp}")
    if len(b) > 3900:
        b = _safe_cut(b, 3900)
    if ev:
        room = max(0, 3900 - len(b) - len("\n\n🔎 <b>Evidence:</b>\n<i></i>") - 2)
        b += f"\n\n🔎 <b>Evidence:</b>\n<i>{_safe_cut(ev, room)}</i>"
    return b

def send_question(chat_id):
    us = u_state(chat_id)
    cur = current_q(us)
    if not cur:
        send_text(chat_id, "🎉 <b>All available quiz sets are complete!</b> More sets coming soon.")
        if not us.get("donate_final"):
            us["donate_final"] = True
            send_donate(chat_id)
        us["active"] = False
        save_state()
        return False
    L, idx, q = cur
    qid = qid_of(L, idx)
    us["today_sent"] += 1
    us["total_done"] += 1
    head, mr, en, opt_lines, png_rows = q_text_block(L, idx, q, us)
    body = f"{head}🇮🇳 {mr}\n\n<b>Options:</b>\n{opt_lines}"
    if len(body) + len(en) < 3900:
        body += f"\n\n🇬🇧 <i>{en}</i>"
        en_sent_inside = True
    else:
        en_sent_inside = False
    if png_rows and PIL_OK:
        shot = None
        try:
            shot = table_png(png_rows)
        except Exception as e:
            print("png render error:", e)
        if shot:
            tg_photo(chat_id, shot, caption=f"📊 <b>Data table — Q {idx + 1}</b>")
        else:
            send_text(chat_id, "📊 <b>Table:</b>\n<pre>" + mono_table(png_rows) + "</pre>")
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

def in_window(ist_now):
    return SEND_HOUR_START <= ist_now.hour < SEND_HOUR_END

def window_notice():
    return ("🌙 Quiz quiet hours (11:00 PM – 6:00 AM IST) — "
            "questions resume at 6:00 AM IST.")

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
        if us.get("donate_day") != us["day"]:
            us["donate_day"] = us["day"]
            send_text(chat_id, "🎉 <b>Today's 90 questions complete!</b> Amazing focus! 🚀")
            send_donate(chat_id)
            save_state()
        return
    if not (SEND_HOUR_START <= now.hour < SEND_HOUR_END):
        return
    if time.time() < us.get("next_due", 0):
        return
    if us.get("pending_qid"):
        # User didn't answer in time: move on silently, no auto-reveal.
        advance(chat_id, when=time.time() + 3)
        return
    send_question(chat_id)

KB_CHANNEL = {"inline_keyboard": [
    [{"text": "🎯 Play Mini App", "url": "https://t.me/Mmindpower_bot/Mmindpower_KBC"},
     {"text": "🤖 Open Bot", "url": "https://t.me/Mmindpower_bot"}],
    [{"text": "📺 Subscribe YouTube", "url": "https://youtube.com/@mmindpower"}]]}

def channel_post(html_text):
    p = {"chat_id": CHANNEL_ID, "text": html_text, "parse_mode": "HTML",
         "disable_web_page_preview": True,
         "reply_markup": KB_CHANNEL}
    r = tg("sendMessage", **p)
    if not r.get("ok"):
        print("channel post failed:", r)
    return bool(r.get("ok"))

def qotd_post(ist_now):
    daynum = int(ist_now.strftime("%Y%j"))
    pool = [(L, i, q) for L in sorted(DATA.keys()) for i, q in enumerate(DATA[L])
            if len(q.get("q_marathi") or "") < 350 and "|" not in (q.get("q_marathi") or "")]
    if not pool:
        return None
    L, i, q = pool[daynum % len(pool)]
    esc = lambda t: html.escape(t or "", quote=False)
    Lset = ["A", "B", "C", "D"]
    opts = "\n".join(f"{Lset[k]}) {esc(o)}" for k, o in enumerate(q["options"][:4]))
    ci = q["correct_index"]
    exp = (q.get("explanation_marathi") or "")[:140]
    sp = f"{Lset[ci]}) {esc(q['options'][ci])}"
    if exp:
        sp += f" — {esc(exp)}"
    return ("❓ <b>Question of the Day</b> ⭐\n\n"
            f"{esc(q['q_marathi'])}\n\n"
            f"{opts}\n\n"
            f"💡 <tg-spoiler>उत्तर: {sp}</tg-spoiler>\n\n"
            "उरले 89+ प्रश्न 👉 t.me/Mmindpower_bot/Mmindpower_KBC"
            "\n🤖 AI doubts/quiz → t.me/Mmindpower_bot?start=qotd"
            "\n📺 Videos → youtube.com/@mmindpower"
            f"\n(Set {L} • Q{i + 1})")

def digest_post(ist_now, today):
    ids = [k for k in USERS if k != "0"]
    st_day = lambda k: (USERS[k].get("stats", {}) or {}).get(today, [0, 0, 0])
    tried = sum(st_day(k)[0] for k in ids)
    ok = sum(st_day(k)[1] for k in ids)
    active_today = sum(1 for k in ids if st_day(k)[0] > 0)
    full = sum(1 for k in ids if USERS[k].get("today_sent", 0) >= DAILY_LIMIT)
    acc = f"{round(ok / tried * 100)}%" if tried else "—"
    return (f"🌙 <b>आजचा Digest — {ist_now.strftime('%d %b')}</b>\n\n"
            f"👩‍🎓 सराव करणारे विद्यार्थी: <b>{active_today}</b>\n"
            f"📝 सोडलेले प्रश्न: <b>{tried}</b>  (🎯 बरोबर: {acc})\n"
            f"🏆 90/90 पूर्ण करणारे: <b>{full}</b>\n\n"
            "उद्या सकाळी 6 वाजता fresh quiz! 🌅\n"
            "📱 t.me/Mmindpower_bot/Mmindpower_KBC  •  🤖 @Mmindpower_bot")

def channel_scheduler(ist_now):
    today = ist_now.strftime("%Y-%m-%d")
    m = meta()
    hh = ist_now.hour
    if hh == 6 and m.get("ch_kick") != today:
        m["ch_kick"] = today
        channel_post("🌅 <b>सुप्रभात! आजचा सराव तयार आहे 📚</b>\n\n"
                     "आजचे <b>90 प्रश्न</b> fresh — Talathi/MPSC 2026 ✨\n"
                     "🤖 Daily quiz → t.me/Mmindpower_bot?start=ch_kick\n"
                     "📱 KBC practice (lifelines सह!) → t.me/Mmindpower_bot/Mmindpower_KBC\n\n"
                     "शिका, जिंका! 🚩")
        save_state(force=True)
    if hh == 12 and m.get("ch_qotd") != today:
        m["ch_qotd"] = today
        post = qotd_post(ist_now)
        if post:
            channel_post(post)
        save_state(force=True)
    if hh == 21 and m.get("ch_dig") != today:
        m["ch_dig"] = today
        channel_post(digest_post(ist_now, today))
        save_state(force=True)

def quiz_tick():
    if not DATA or not USERS:
        return
    now = datetime.datetime.now(IST)
    for k in list(USERS.keys()):
        try:
            tick_user(int(k), now)
        except Exception as e:
            print("tick err", k, e)
    channel_scheduler(now)


MILESTONES = [10, 25, 50, 100, 250, 500, 1000, 2000, 5000]

def meta():
    m = USERS.setdefault("0", default_state())
    m["active"] = False
    return m

def mark_seen(chat_id):
    k = str(chat_id)
    is_new = k not in USERS
    us = u_state(chat_id)
    nowts = time.time()
    if not us.get("first_seen"):
        us["first_seen"] = nowts
    us["last_seen"] = nowts
    if is_new and k != "0":
        total = len([x for x in USERS if x != "0"])
        if total in MILESTONES and total > meta().get("ms_signaled", 0):
            meta()["ms_signaled"] = total
            send_text(OWNER_CHAT,
                      f"🎉🎉🎉 <b>MILESTONE: {total} STUDENTS!</b>\n\n"
                      f"Mmindpower Bot just got its <b>{total}th</b> user! 🚀")

def record_try(chat_id, qid, correct):
    us = u_state(chat_id)
    done = us.setdefault("done", {})
    if qid in done or len(done) >= 900:
        return
    done[qid] = 1 if correct else 0
    today = datetime.datetime.now(IST).strftime("%Y-%m-%d")
    st = us.setdefault("stats", {})
    row = st.setdefault(today, [0, 0, 0])
    if correct:
        row[1] += 1
    else:
        row[2] += 1
    row[0] += 1
    if len(st) > 30:
        for old_d in sorted(st.keys())[:-30]:
            del st[old_d]

def _day0_ts(ist_now):
    return ist_now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()

def report_card(chat_id):
    us = u_state(chat_id)
    st = us.get("stats", {}) or {}
    done = us.get("done", {}) or {}
    ist = datetime.datetime.now(IST)
    today = ist.strftime("%Y-%m-%d")
    tr, ok, bad = st.get(today) or [0, 0, 0]
    acc_t = f"{round(ok / tr * 100)}%" if tr else "—"
    NL = "\n"
    lines = ["🏆 <b>Mmindpower Report Card</b>", "",
             f"📅 <b>Today ({ist.strftime('%d %b')})</b>",
             f"📝 Tried {tr} | ✅ {ok} | ❌ {bad} | 🎯 {acc_t}"]
    past = sorted([d for d in st.keys() if d != today], reverse=True)
    for d in past[:3]:
        t2, o2, _b2 = st[d]
        a2 = f"{round(o2 / t2 * 100)}%" if t2 else "—"
        dd = datetime.datetime.strptime(d, "%Y-%m-%d").strftime("%d %b")
        lines.append(f"📅 {dd}: {t2} tried | 🎯 {a2}")
    lines.append("")
    streak = 0
    cur = ist.date() if tr > 0 else ist.date() - datetime.timedelta(days=1)
    while cur.strftime("%Y-%m-%d") in st and st[cur.strftime("%Y-%m-%d")][0] > 0:
        streak += 1
        cur -= datetime.timedelta(days=1)
    lines.append(f"🔥 Streak: {streak} day{'s' if streak != 1 else ''}")
    total_q = 90 * len(DATA)
    tried = len(done)
    pct = round(tried / total_q * 100) if total_q else 0
    lines.append(f"🚀 Journey: {tried}/{total_q} questions ({pct}%)")
    order = sorted(DATA.keys())
    parts = []
    for L in order:
        if L < us["set"]:
            parts.append(f"Set {L} ✔")
        elif L == us["set"]:
            parts.append(f"Set {L} ➤Q{us['index'] + 1}")
        else:
            parts.append(f"Set {L} ⬛")
    lines.append("   " + " • ".join(parts))
    tr_all = sum(r[0] for r in st.values())
    ok_all = sum(r[1] for r in st.values())
    acc_all = f"{round(ok_all / tr_all * 100)}%" if tr_all else "—"
    lines.append(f"✅ Accuracy overall: {acc_all}")
    best = None
    for d, r in st.items():
        t2, o2, _ = r
        if t2 >= 3 and (best is None or (o2 / t2) > best[1]):
            best = (d, o2 / t2)
    if best:
        dd = datetime.datetime.strptime(best[0], "%Y-%m-%d").strftime("%d %b")
        lines.append(f"🏅 Best day: {dd} ({round(best[1] * 100)}%)")
    rem = max(0, DAILY_LIMIT - us["today_sent"])
    lines.append(f"⏳ Today remaining: {rem}/{DAILY_LIMIT}")
    return NL.join(lines)

def audience_report():
    ids = [k for k in USERS if k != "0"]
    if not ids:
        return "📈 No users registered yet."
    ist = datetime.datetime.now(IST)
    today = ist.strftime("%Y-%m-%d")
    day0 = _day0_ts(ist)
    week0 = (ist - datetime.timedelta(days=7)).timestamp()
    total = len(ids)
    new_today = sum(1 for k in ids if (USERS[k].get("first_seen") or 0) >= day0)
    act_today = sum(1 for k in ids if (USERS[k].get("last_seen") or 0) >= day0)
    act_week = sum(1 for k in ids if (USERS[k].get("last_seen") or 0) >= week0)
    quizzers = sum(1 for k in ids if USERS[k].get("done") or USERS[k].get("total_done", 0) > 0)
    tr = sum((USERS[k].get("stats", {}) or {}).get(today, [0, 0, 0])[0] for k in ids)
    ok = sum((USERS[k].get("stats", {}) or {}).get(today, [0, 0, 0])[1] for k in ids)
    acc = f"{round(ok / tr * 100)}%" if tr else "—"
    fan_k, fan_n = None, 0
    for k in ids:
        n = len(USERS[k].get("done", {}) or {})
        if n > fan_n:
            fan_k, fan_n = k, n
    fan = "—"
    if fan_k:
        z = str(fan_k)
        fan = f"{z[:2]}xxx{z[-2:]} ({fan_n} questions)"
    mm = meta()
    srcs = ", ".join(f"{k[4:]}:{v}" for k, v in sorted(mm.items()) if k.startswith("src_")) or "—"
    NL = "\n"
    return (f"📈 <b>Mmindpower Audience Report</b>{NL}{NL}"
            f"👥 Total users: <b>{total}</b>{NL}"
            f"🆕 New today: {new_today}{NL}"
            f"⚡ Active today: {act_today}{NL}"
            f"📆 Active last 7 days: {act_week}{NL}{NL}"
            f"📚 Quiz players: {quizzers}{NL}"
            f"🤖 AI-chat only: {total - quizzers}{NL}"
            f"📝 Tried today (all users): {tr} | 🎯 {acc}{NL}{NL}"
            f"🎖️ Superfan: {fan}{NL}{NL}"
            f"📣 Sources: {srcs}")

def maybe_send_digest():
    ist = datetime.datetime.now(IST)
    if ist.hour != 23 or ist.minute < 50:
        return
    today = ist.strftime("%Y-%m-%d")
    m = meta()
    if m.get("digest_day") == today:
        return
    m["digest_day"] = today
    ids = [k for k in USERS if k != "0"]
    day0 = _day0_ts(ist)
    new_today = sum(1 for k in ids if (USERS[k].get("first_seen") or 0) >= day0)
    tr = sum((USERS[k].get("stats", {}) or {}).get(today, [0, 0, 0])[0] for k in ids)
    ok = sum((USERS[k].get("stats", {}) or {}).get(today, [0, 0, 0])[1] for k in ids)
    acc = f"{round(ok / tr * 100)}%" if tr else "—"
    send_text(OWNER_CHAT,
              f"🌙 <b>Day Report — {ist.strftime('%d %b')}</b>\n\n"
              f"👥 Users: {len(ids)} (+{new_today} new)\n"
              f"📝 Questions tried: {tr} | 🎯 {acc}\n"
              f"📚 Tomorrow: fresh 90 questions ready. 😴")
    save_state(force=True)

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

    if kind == "memrecheck":
        if is_member(chat_id, force=True):
            ack("🎉 +30 AI chats unlocked!")
            send_text(chat_id, "🎖️ <b>Channel member confirmed!</b> +30 AI chats every day — आजपासूनच! 💬")
        else:
            ack("अजून member दिसत नाही 🙈")
            send_text(chat_id, "🔍 अजून membership दिसत नाही — पहिले @mmindpower_1 join करा, मग पुन्हा re-check दाबा 🙂")
        return

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
        record_try(chat_id, qid, chosen == ci)
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
        if in_window(datetime.datetime.now(IST)):
            tail = "First question arriving now! 🚀"
        else:
            tail = window_notice() + "\nYour Day {d} quiz will auto-start at 6:00 AM. ⏰".format(d=day_no)
        edit_text(chat_id, msg_id,
                  f"✅ <b>Restarted: Day {day_no} — Set {L}</b> (from Q{start + 1})\n" + tail)
        ack("Reset done!")
        quiz_tick()

    elif kind == "pickcancel":
        edit_text(chat_id, msg_id, "❌ Reset cancelled — your progress is unchanged.")
        ack()

    elif kind == "go":
        act = parts[1] if len(parts) > 1 else "start"
        do_quiz_action(chat_id, act)
        ack()

    elif kind == "next":
        qid = parts[1] if len(parts) > 1 else ""
        if cur and qid == cur_qid:
            advance(chat_id, when=0)
        else:
            us["next_due"] = min(us.get("next_due", 0), time.time())
            save_state()
        quiz_tick()
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

def do_quiz_action(chat_id, action):
    us = u_state(chat_id)
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
        send_text(chat_id, report_card(chat_id))
    else:
        us["active"] = True
        if us.get("pending_qid") is None:
            us["next_due"] = 0
        save_state()
        if in_window(datetime.datetime.now(IST)):
            send_text(chat_id, "▶️ Quiz resumed/started — next question coming right up!")
        else:
            send_text(chat_id, "▶️ Quiz is active! " + window_notice())
        quiz_tick()

HELP_PHRASES = [
    "how to play", "how to use", "how do i use", "how do i play", "how to start",
    "how can i play", "how can i use", "how can i start", "how to quiz", "quiz how",
    "what commands", "which commands", "which command", "what command", "all commands",
    "command list", "list of commands", "commands list", "show commands", "give commands",
    "tell me commands", "send commands", "commands batao", "command batao",
    "how this bot works", "how does this bot work", "how does it work",
    "what can you do", "what do you do", "what all can you do",
    "guide me", "show guide", "instructions", "tutorial", "how to operate",
    "kaise khele", "kaise khelu", "kaise use", "kese use", "kaunse command",
    "kya command", "commands ke bare", "help me use",
]
HELP_TOKENS = ("command", "commands", "कमांड", "कमांड्स")

RESTART_PHRASES = [
    "restart", "start over", "start again", "begin again", "replay",
    "from the beginning", "from beginning", "from day 1", "from day one",
    "from first", "fresh start", "reset quiz", "quiz reset", "reset my quiz",
    "phir se shuru", "fir se shuru", "dobara shuru", "dobara start",
    "naye se shuru", "nayi se shuru", "restart karo", "reset karo",
    "phir se karo", "fir se karo", "dobara karo",
    "पहिल्यापासून", "पहिल्या पासून", "पुन्हा सुरू करा", "पुन्हा सुरू",
    "नवीन सुरू", "नव्याने सुरू", "नव्याने सुरु", "पुन्हा करा", "रीस्टार्ट",
    "परत सुरू", "परत सुरु", "सुरुवातीपासून",
]

def wants_restart(t):
    t = t.lower().strip()
    return any(p in t for p in RESTART_PHRASES)

def wants_help(t):
    t = t.lower().strip()
    if t in ("help", "?", "??", "menu", "help!"):
        return True
    for p in HELP_PHRASES:
        if p in t:
            return True
    if any(w in t for w in HELP_TOKENS):
        if any(q in t for q in ("what", "which", "how", "list", "all", "give", "show",
                                "bata", "batao", "dya", "sanga", "कसे", "काय", "क्या")) or t.endswith("?"):
            return True
    if "how" in t and any(w in t for w in ("play", "use", "start", "quiz", "this bot")):
        return True
    if any(w in t for w in ("कसे", "कसं")) and any(w in t for w in ("खेळ", "वापर", "सुरू")):
        return True
    return False

GUIDE = (
    "🎯 <b>How to use Mmindpower Bot</b>\n\n"
    "📚 <b>Daily Quiz</b> — 90 questions per day:\n"
    "1️⃣ Tap ▶️ <b>Start Quiz</b> below (or /quiz)\n"
    "2️⃣ A question arrives with 🅰️🅱️🅲🅳 buttons — tap your answer\n"
    "3️⃣ See ✅/❌ instantly, then 📖 Show Explanation (tap again to 🙈 Hide)\n"
    "4️⃣ Next question comes automatically (~2 min)\n"
    "5️⃣ Don't answer within 10 min? Bot moves on silently — buttons still work later!\n\n"
    "🤖 <b>AI chat</b> — just type any question normally.\n\n"
    "⌨️ <b>Commands</b>\n"
    "/quiz — start/resume • /quiz_pause — pause • /quiz_resume — resume\n"
    "/quiz_status — progress • /quiz_reset — restart any day\n"
    "/reset — clear AI memory • /help — help"
)

def kb_guide():
    return {"inline_keyboard": [
        [{"text": "▶️ Start Quiz", "callback_data": "go|start"}],
        [{"text": "📊 My Status", "callback_data": "go|status"},
         {"text": "🔄 Pick a Day", "callback_data": "go|reset"}],
        [{"text": "⏸ Pause Quiz", "callback_data": "go|pause"}]]}

MEMBER_BONUS = 30

def is_member(chat_id, force=False):
    us = USERS.setdefault(str(chat_id), default_state())
    today = datetime.datetime.now(IST).strftime("%Y-%m-%d")
    if force or us.get("mem_day") != today:
        r = tg("getChatMember", chat_id=CHANNEL_ID, user_id=chat_id)
        st = ((r.get("result") or {}).get("status")) if r.get("ok") else None
        us["mem_ok"] = st in ("member", "administrator", "creator")
        us["mem_day"] = today
    return bool(us.get("mem_ok"))

def ai_gate(chat_id):
    """Count + enforce the daily AI-chat quota. True = allowed, slot consumed."""
    if chat_id == OWNER_CHAT:
        return True
    us = USERS.setdefault(str(chat_id), default_state())
    today = datetime.datetime.now(IST).strftime("%Y-%m-%d")
    if us.get("ai_day") != today:
        us["ai_day"] = today
        us["ai_today"] = 0
    used = us.get("ai_today", 0)
    member = is_member(chat_id)
    limit = AI_DAILY_LIMIT + (MEMBER_BONUS if member else 0)
    if used >= limit:
        cap = (f"🧠 <b>AI chat limit reached ({limit}/day)!</b>\n"
               "Fresh quota at midnight 🌅 — meanwhile the quiz never stops 📚 /quiz")
        kb = None
        if not member:
            cap += ("\n\n📢 <b>PS:</b> @mmindpower_1 channel members get <b>+30 AI chats/day</b>!")
            kb = {"inline_keyboard": [
                [{"text": "📢 Join @mmindpower_1", "url": "https://t.me/mmindpower_1"}],
                [{"text": "✅ Joined — re-check", "callback_data": "memrecheck"}]]}
        send_text(chat_id, cap, reply_markup=kb)
        save_state()
        return False
    us["ai_today"] = used + 1
    warn_at = limit - 15
    if us["ai_today"] == warn_at:
        send_text(chat_id, "🧠 Heads-up: 15 AI chats left today "
                           "(resets at midnight). Quiz is always unlimited 📚")
    save_state()
    return True

def handle(update):
    msg = update.get("message") or {}
    text = (msg.get("text") or "").strip()
    chat = msg.get("chat") or {}
    chat_id, user = chat.get("id"), msg.get("from") or {}
    if chat_id is None:
        return
    mark_seen(chat_id)
    if chat_id not in APP_MENU_DONE:
        APP_MENU_DONE.add(chat_id)
        tg("setChatMenuButton", chat_id=chat_id, menu_button={
            "type": "web_app", "text": "📚 Practice App",
            "web_app": {"url": APP_URL_V}})
    token0 = text.split()[0].split("@")[0].lower() if text.startswith("/") else ""
    if token0 == "/audience":
        if chat_id == OWNER_CHAT:
            send_text(chat_id, audience_report())
        return
    if token0 == "/donate":
        send_donate(chat_id)
        return
    if token0 == "/app":
        send_text(chat_id, "📚 <b>Mmindpower Practice App</b> — all sets, any time 👇",
                  reply_markup={"inline_keyboard": [[{"text": "📚 Open Practice App", "web_app": {"url": APP_URL_V}}]]})
        return
    if token0 == "/announce":
        if chat_id == OWNER_CHAT:
            body = text[len("/announce"):].strip()
            if body:
                ok = channel_post(body)
                send_text(chat_id, "📣 Channel ला पोस्ट झाले! ✅" if ok else
                          "⚠️ Failed — bot @mmindpower_1 मध्ये <b>admin</b> आहे का? (Post Messages right लागेल 👮)")
            else:
                send_text(chat_id, "वापर: /announce <मेसेज> — HTML tags चालतात (<b>, <tg-spoiler>)")
        return
    if token0 in ("/quiz", "/quiz_pause", "/quiz_resume", "/quiz_reset", "/quiz_status"):
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
        do_quiz_action(chat_id, action)
        return
    cmd = text.split()[0].split("@")[0].lower() if text.startswith("/") else None
    if cmd == "/start":
        parts = text.split()
        if len(parts) > 1:
            src_tag = parts[1].strip().lower()[:24]
            us = USERS.setdefault(str(chat_id), default_state())
            if src_tag and not us.get("src"):
                us["src"] = src_tag
                mm = meta()
                mm["src_" + src_tag] = mm.get("src_" + src_tag, 0) + 1
                save_state()
        send_text(chat_id, WELCOME,
                  reply_markup={"inline_keyboard": [
                      [{"text": "📣 Join @mmindpower_1", "url": "https://t.me/mmindpower_1"}],
                      [{"text": "🎯 Open Mini App", "web_app": {"url": APP_URL_V}},
                       {"text": "📺 YouTube", "url": "https://youtube.com/@mmindpower"}]]})
    elif cmd == "/help":
        send_text(chat_id, HELP)
    elif cmd == "/about":
        send_text(chat_id, ABOUT)
    elif cmd == "/reset":
        MEM.pop(chat_id, None)
        send_text(chat_id, "🧹 Chat memory cleared. Fresh start!")
    elif text and wants_restart(text):
        send_text(chat_id, "🔄 <b>Restart quiz</b> — pick the day you want to restart from 👇",
                  reply_markup=kb_daypicker())
    elif text and wants_help(text):
        send_text(chat_id, GUIDE, reply_markup=kb_guide())
    elif text:
        if not ai_gate(chat_id):
            return
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
        {"command": "donate", "description": "☕ Support Mmindpower (optional ₹5)"},
        {"command": "app", "description": "📚 Practice app (all sets)"},
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
            if time.time() - last_tick > 2:
                quiz_tick()
                maybe_send_digest()
                last_tick = time.time()
            params = {"timeout": 4, "allowed_updates": ["message", "callback_query"]}
            if offset:
                params["offset"] = offset
            data = requests.post(f"{TG}/getUpdates", json=params, timeout=15).json()
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
