#!/usr/bin/env python3
"""Mmindpower Explainer Wing — a topic in -> a ~5-min branded Marathi explainer video out.
Pipeline: Wikipedia(-mr, free) grounding -> Groq composes a chaptered script (strict JSON)
-> PIL cinema cards (concept/def/compare/steps/quiz-bite kinds) -> neural TTS -> ffmpeg assembly.
Usage: python3 tools/video_explainer.py --topic "..." [--voice mr-IN-ManoharNeural] [--preview] [--script-cache out_explainer/script.json]
"""
import os, sys, json, glob, random, subprocess, argparse, time, datetime, re

from PIL import Image, ImageDraw, ImageFont, ImageFilter
from groq2stage import groq_script_2stage, quiz_hinglish

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT_B = os.path.join(ROOT, "assets", "fonts", "NotoSansDevanagari-Bold.ttf")
OUT = os.path.abspath(os.path.join(ROOT, "out_explainer"))
W, H, FPS = 1920, 1080, 30
BRAND = "Mmindpower"
NAVY1, NAVY2 = (8, 18, 44), (22, 52, 110)
GOLD, GREEN, CYAN, WHITE, MUTE = (255, 199, 95), (74, 222, 128), (113, 199, 236), (246, 249, 255), (168, 186, 214)
ROSE = (240, 150, 160)


def say(m): print(time.strftime("[%H:%M:%S]"), m, flush=True)
def run(cmd):
    say("ffmpeg: " + os.path.basename(cmd[-1]))
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)

def dur_of(path, default=2.0):
    try:
        import subprocess
        p = subprocess.run(["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                            "-of", "csv=p=0", path], capture_output=True, text=True, timeout=15)
        d = float(p.stdout.strip());  return max(d, 0.5)
    except Exception:
        try:
            if path.endswith(".mp3"):
                from mutagen.mp3 import MP3
                return max(MP3(path).info.length, 0.5)
            if path.endswith(".mp4"):
                from mutagen.mp4 import MP4
                return max(MP4(path).info.length, 0.5)
        except Exception:
            pass
        return default

def bg(accent=NAVY2):
    img = Image.new("RGB", (W, H), NAVY1)
    for y in range(H):
        t = y / H
        img.paste((int(NAVY1[0]+(accent[0]-NAVY1[0])*t), int(NAVY1[1]+(accent[1]-NAVY1[1])*t),
                   int(NAVY1[2]+(accent[2]-NAVY1[2])*t)), (0, y, W, y+1))
    glow = Image.new("L", (W, H), 0); gd = ImageDraw.Draw(glow)
    gd.ellipse((W-560, -260, W+180, 300), fill=70); gd.ellipse((-320, H-420, 300, H+150), fill=45)
    img.paste(Image.new("RGB", (W, H), GOLD), (0, 0), glow.filter(ImageFilter.GaussianBlur(120)))
    v = Image.new("L", (W, H), 0); ImageDraw.Draw(v).rounded_rectangle((0,0,W,H), 200, fill=110)
    img.paste(Image.new("RGB", (W, H), (0,0,0)), (0, 0), Image.eval(v, lambda p: max(0, 110-p)))
    return img

def font(s): return ImageFont.truetype(FONT_B, s)

def fit(d, text, maxw, start, floor=34):
    s = start
    while s > floor and d.textlength(text, font=font(s)) > maxw: s -= 3
    return font(s)

def wrap(d, text, fnt, maxw):
    words, lines, cur = text.split(), [], ""
    for wd in words:
        t = (cur + " " + wd).strip()
        if d.textlength(t, font=fnt) <= maxw: cur = t
        else:
            lines.append(cur or wd); cur = "" if not cur else wd
    if cur: lines.append(cur)
    return lines

def chrome(img, tag="", chapters=None, cur=0):
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, 12), fill=GOLD)
    d.text((70, H-68), BRAND + "  •  Explainer", font=font(38), fill=MUTE)
    d.text((W-70, H-68), tag, font=font(38), fill=MUTE, anchor="ra")
    if chapters:
        n = len(chapters); bw = min(120, (W-420)//max(n,1) - 18)
        x0 = (W - (n*(bw+18)))//2
        for k, c in enumerate(chapters):
            col = GOLD if k == cur else (56, 76, 122)
            d.rounded_rectangle((x0+k*(bw+18), 46, x0+k*(bw+18)+bw, 96), 10, outline=col, width=3)
            lbl = c[:14] + ("…" if len(c) > 14 else "")
            d.text((x0+k*(bw+18)+bw/2, 71), lbl, font=fit(d, lbl, bw-14, 30, 20), fill=(WHITE if k == cur else MUTE), anchor="mm")
    return img

def title_card(topic, chips):
    img = bg(); d = ImageDraw.Draw(img)
    d.text((W//2, 190), BRAND + " Explains", font=font(88), fill=GOLD, anchor="mm")
    d.text((W//2, 520), topic, font=fit(d, topic, 1560, 108), fill=WHITE, anchor="mm")
    y = 700
    for c in chips[:4]:
        tw = d.textlength(c, font=font(44)) + 70
        d.rounded_rectangle((W//2-tw/2, y, W//2+tw/2, y+76), 38, outline=CYAN, width=4)
        d.text((W//2, y+38), c, font=font(44), fill=CYAN, anchor="mm"); y += 100
    return chrome(img)

def map_card(chapters):
    img = bg(); d = ImageDraw.Draw(img)
    d.text((W//2, 190), ("Aaj Ka Safar" if CFG["lang"] == "hinglish" else "आजची शिखर-यात्रा"), font=font(96), fill=GOLD, anchor="mm")
    y = 330
    for i, c in enumerate(chapters):
        d.rounded_rectangle((270, y, 390, y+70), 14, fill=(24, 48, 98), outline=GOLD, width=3)
        d.text((330, y+35), str(i+1), font=font(44), fill=GOLD, anchor="mm")
        d.text((440, y+17), c, font=fit(d, c, 1200, 50), fill=WHITE)
        y += 96
    return chrome(img, chapters=chapters)

KIND_LABELS = {"concept": "संकल्पना", "compare": "तुलना", "steps": "पायऱ्या", "def": "व्याख्या"}
FALLBACK_SIDES = ["बाजू १", "बाजू २"]
CFG = {"lang": "mr"}

def section_card(idx, chapters, heading, kind, bullets, chips):
    img = bg(); d = ImageDraw.Draw(img)
    kind_icon = KIND_LABELS.get(kind, KIND_LABELS["concept"])
    d.text((W//2, 180), heading, font=fit(d, heading, 1500, 72, 42), fill=GOLD, anchor="mm")
    d.text((170, 165), kind_icon, font=fit(d, kind_icon, 300, 46, 30), fill=CYAN)
    if kind == "compare" and len(bullets) >= 2:
        halves = [bullets[:len(bullets)//2] or bullets[:1], bullets[len(bullets)//2:]]
        labels = chips[:2] if len(chips) >= 2 else FALLBACK_SIDES
        for col, (hb, lab) in enumerate(zip(halves, labels)):
            x0 = 140 + col*((W-280)//2); xw = (W-280)//2 - 40
            d.rounded_rectangle((x0, 290, x0+xw, 900), 22, fill=(14, 30, 66), outline=(70,100,168), width=3)
            d.rounded_rectangle((x0, 290, x0+xw, 360), 22, fill=GOLD)
            d.text((x0+xw/2, 325), lab, font=fit(d, lab, xw-60, 44, 28), fill=NAVY1, anchor="mm")
            yb = 400
            for b in hb[:6]:
                for l_, ln in enumerate(wrap(d, b, font(40), xw-90)[:2]):
                    d.text((x0+36, yb), ("• " if l_ == 0 else "   ") + ln, font=font(40), fill=WHITE)
                    yb += 60
    elif kind == "steps":
        y = 300
        for j, b in enumerate(bullets[:5]):
            d.rounded_rectangle((140+j*20, y, 140+j*20+90, y+66), 12, fill=GOLD)
            d.text((140+j*20+45, y+33), str(j+1), font=font(42), fill=NAVY1, anchor="mm")
            for l_, ln in enumerate(wrap(d, b, font(44), 1400)[:2]):
                d.text((260+j*20, y + (4 if l_ == 0 else 56)), ln, font=font(44), fill=WHITE)
            y += 118
    elif kind == "def" and bullets:
        d.rounded_rectangle((140, 300, W-140, 560), 26, fill=(52, 40, 8), outline=GOLD, width=6)
        y = 330
        for ln in wrap(d, bullets[0], font(50), W-420)[:3]:
            d.text((180, y), ln, font=font(50), fill=GOLD); y += 80
        y = 640
        for b in bullets[1:4]:
            for ln in wrap(d, b, font(42), 1500)[:2]:
                d.text((160, y), "✦ " + ln, font=font(42), fill=WHITE); y += 66
    else:
        y = 300
        for b in bullets[:6]:
            for l_, ln in enumerate(wrap(d, b, font(46), 1500)[:2]):
                d.text((170, y), ("◉ " if l_ == 0 else "   ") + ln, font=font(46), fill=WHITE)
                y += 70
    if chips and kind not in ("compare",):
        c = chips[0]; tw = d.textlength(c, font=font(40)) + 56
        d.rounded_rectangle((W-140-tw, H-160, W-140, H-100), 30, fill=(24, 48, 98), outline=CYAN, width=3)
        d.text((W-140-tw/2, H-130), c, font=font(40), fill=CYAN, anchor="mm")
    return chrome(img, f"{idx+1}/{len(chapters)}", chapters, idx)

def quiz_card(i, n, q):
    hi = CFG["lang"] == "hinglish"
    img = bg((10, 44, 40)); d = ImageDraw.Draw(img)
    d.text((W//2, 170), ("— QUICK QUIZ CHECK —" if hi else "✦ जलद तपासणी ✦"), font=font(80), fill=GREEN, anchor="mm")
    y = 290
    qtext = (q.get("q_hi") or q["q_marathi"]) if hi else q["q_marathi"]
    for ln in wrap(d, qtext, font(50), 1560)[:3]:
        d.text((170, y), ln, font=font(50), fill=WHITE); y += 76
    y += 16
    opts = (q.get("options_hi") or q["options"]) if hi else q["options"]
    for jnn, opt in enumerate(opts[:4]):
        d.text((230, y), f"{'ABCD'[jnn]})", font=font(44), fill=GOLD)
        d.text((330, y), str(opt)[:80], font=fit(d, str(opt), 1350, 44, 32), fill=WHITE); y += 82
    d.text((W//2, H-170), ("Answer turant aane wala hai — bane raho!" if hi else "उत्तरही लगेचच — पाहत राहा!"), font=font(44), fill=MUTE, anchor="mm")
    return chrome(img, f"quiz {i+1}/{n}")

def quiz_answer_card(i, n, q):
    hi = CFG["lang"] == "hinglish"
    img = bg((10, 44, 40)); d = ImageDraw.Draw(img)
    ci = q.get("correct_index", 0)
    opts = (q.get("options_hi") or q["options"]) if hi else q["options"]
    ex = ((q.get("explain_hi") or q.get("explanation_marathi")) or "") if hi else (q.get("explanation_marathi") or "")
    d.text((W//2, 200), f"{'SAHI JAWAAB' if hi else 'उत्तर'}: {'ABCD'[ci]}", font=font(96), fill=GREEN, anchor="mm")
    d.text((W//2, 330), str(opts[ci])[:100], font=fit(d, str(opts[ci]), 1500, 52), fill=WHITE, anchor="mm")
    y = 470
    for ln in wrap(d, ex[:400], font(46), 1500)[:5]:
        d.text((160, y), ln, font=font(46), fill=WHITE); y += 70
    return chrome(img, f"quiz {i+1}/{n}")

def recap_card(recap):
    img = bg(); d = ImageDraw.Draw(img)
    d.text((W//2, 200), ("— EK NAZAR MEIN —" if CFG["lang"] == "hinglish" else "✦ एका नजरेत ✦"), font=font(92), fill=GOLD, anchor="mm")
    y = 330
    for ln in wrap(d, recap, font(52), 1500)[:7]:
        d.text((W//2, y), ln, font=font(52), fill=WHITE, anchor="mm"); y += 82
    return chrome(img)

def cta_card(cta):
    img = bg(); d = ImageDraw.Draw(img)
    d.text((W//2, 260), BRAND, font=font(140), fill=GOLD, anchor="mm")
    y = 470
    for ln in wrap(d, cta, font(52), 1450)[:4]:
        d.text((W//2, y), ln, font=font(52), fill=WHITE, anchor="mm"); y += 80
    d.rounded_rectangle((W//2-300, H-320, W//2+300, H-210), 42, fill=(200, 40, 40))
    d.text((W//2, H-265), "SUBSCRIBE", font=font(52), fill=WHITE, anchor="mm")
    d.text((W//2, H-150), "Telegram: @mmindpower_1  •  YouTube: @mmindpower", font=font(44), fill=MUTE, anchor="mm")
    return chrome(img)

def thumbnail(topic, chips):
    img = bg(); d = ImageDraw.Draw(img)
    d.text((W//2, 260), "EXPLAINED", font=font(80), fill=CYAN, anchor="mm")
    d.text((W//2, 470), topic, font=fit(d, topic, 1600, 118), fill=WHITE, anchor="mm")
    if chips:
        d.text((W//2, 640), chips[0], font=fit(d, chips[0], 1500, 54), fill=GOLD, anchor="mm")
    d.rectangle((0, H-240, W, H), fill=(0, 0, 0))
    d.text((W//2, H-120), "Mmindpower • 5-min Explainer", font=font(88), fill=GOLD, anchor="mm")
    return img


# ------------------ voice aliases (free-stack child/vernacular faking) ------------------
VOICE_ALIAS = {
    "manohar":        ("mr-IN-ManoharNeural", "+0Hz", "+6%"),
    "aarohi":         ("mr-IN-AarohiNeural", "+0Hz", "+4%"),
    "aarohi_child":   ("mr-IN-AarohiNeural", "+50Hz", "+10%"),   # pitch-up → childlike
    "kolhapur_child": ("mr-IN-AarohiNeural", "+50Hz", "+10%"),
    "kolhapuri_child":("mr-IN-AarohiNeural", "+50Hz", "+10%"),
    "child":          ("mr-IN-AarohiNeural", "+50Hz", "+10%"),
}

def resolve_voice(name):
    n = (name or "").strip().lower()
    if not n:  # language-driven default
        return None
    if n in VOICE_ALIAS:
        ev, pitch, rate = VOICE_ALIAS[n]
        say(f"voice alias '{name}' → {ev} pitch={pitch} rate={rate}")
        return ev, pitch, rate
    if n.startswith("mr-in-"):
        say(f"voice literal {name}")
        return name, "+0Hz", "+6%"
    say(f"voice '{name}' unknown → default Manohar")
    return "mr-IN-ManoharNeural", "+0Hz", "+6%"


# ------------------ audio: chimes + dual TTS ------------------
def synth_chime(path, dur=1.1, sr=44100):
    import wave, struct, math
    N = int(dur*sr); frames = bytearray()
    for i in range(N):
        t = i/sr
        f = 880 if t < 0.5 else 1320
        env = math.exp(-3.4*t)
        frames += struct.pack('<h', int(12000*env*math.sin(2*math.pi*f*t)))
    wv = wave.open(path, 'wb'); wv.setparams((1, 2, sr, N, 'NONE', 'not compressed'))
    wv.writeframes(bytes(frames)); wv.close()

async def tts_all(tasks, voice, pitch="+0Hz", rate="+6%"):
    try:
        import edge_tts; edge_ok = True
    except Exception:
        edge_ok = False
    for text, path in tasks:
        os.makedirs(os.path.dirname(path), exist_ok=True); done = False
        if edge_ok:
            try:
                import asyncio as _a
                comm = edge_tts.Communicate(text=text[:1800], voice=voice, rate=rate, pitch=pitch)
                async def _w():
                    with open(path, "wb") as fh:
                        async for ch in comm.stream():
                            if ch["type"] == "audio": fh.write(ch["data"])
                await _a.wait_for(_w(), timeout=55)
                done = os.path.getsize(path) > 2000
                say(f"tts[edge] → {os.path.basename(path)}")
            except Exception as e:
                say(f"tts[edge] fail {str(e)[:70]} → gTTS")
        if not done:
            try:
                from gtts import gTTS; import asyncio as _a
                def _g(): gTTS(text=text[:1500], lang="mr").save(path)
                await _a.wait_for(_a.get_event_loop().run_in_executor(None, _g), timeout=55)
                done = os.path.getsize(path) > 2000
                say(f"tts[gtts] → {os.path.basename(path)}")
            except Exception as e:
                say(f"tts[gtts] fail {str(e)[:70]}")
        if not done:
            subprocess.run(["ffmpeg","-y","-f","lavfi","-i","anullsrc=r=44100:cl=mono","-t","6","-q:a","9","-acodec","libmp3lame",path],
                           check=False, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)


# ------------------ grounding + script ------------------
UA = {"User-Agent": "MmindpowerExplainer/1.0 (educational open-content use)"}

def wiki_ground(topic):
    """Search -> best title -> REST summary (never silently empty: always narrates its path)."""
    import requests
    for lang in ("mr", "en"):
        try:
            sr = requests.get(f"https://{lang}.wikipedia.org/w/api.php",
                              params={"action": "opensearch", "search": topic, "limit": 3,
                                      "namespace": 0, "format": "json"}, headers=UA, timeout=30)
            hits = sr.json()[1] if isinstance(sr.json(), list) else []
            say(f"wiki[{lang}] search hits: {hits[:2]}")
            for title in hits[:2] or [topic]:
                try:
                    sm = requests.get(f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{requests.utils.quote(title)}",
                                      headers=UA, timeout=30)
                    if sm.status_code == 200:
                        txt = (sm.json().get("extract") or "").strip()
                        if len(txt) > 150:
                            say(f"wiki[{lang}] grounded via '{title}': {len(txt)} chars")
                            return txt[:3500]
                except Exception as e:
                    say(f"wiki[{lang}] summary err: {str(e)[:60]}")
        except Exception as e:
            say(f"wiki[{lang}] search skip: {str(e)[:60]}")
    say("wiki: no grounding found (continuing with model knowledge only)")
    return ""

def groq_script(topic, ground, nsec, dialect="", lang="mr", seed=None):
    s2 = groq_script_2stage(topic, ground, nsec, OUT, dialect=dialect, lang=lang, seed=seed)
    if s2:
        return s2
    gk = os.environ.get("GROQ_KEY")
    schema = {
        "title": topic,
        "hook": "2-line energetic Marathi welcome & promise",
        "chapters": [
            {"heading": "short Marathi heading (<= 7 words)",
             "narration": "Marathi spoken explanation, 55-85 words, plain spoken register",
             "bullets": ["<= 12 words each", "3-6 bullets"],
             "kind": "concept|compare|steps|def",
             "chips": ["2-4 word keyword chip"]
            } for _ in range(nsec)],
        "recap": "2-3 sentence Marathi recap",
        "cta": "2-line Marathi subscribe+Telegram CTA (@mmindpower_1)"}
    if gk:
        import requests
        example = {"title": topic, "hook": "नमस्कार! आज आपण सोप्या भाषेत समजून घेणार आहोत या विषयाचा सारा खजिना.",
                   "chapters": [{"heading": "परीचय आणि मूलभूत चौकट", "narration": "पन्नास ते ऐंशी शब्दांत सहज बोलले जाणारे मराठी वर्णन…", "bullets": ["मुद्दा एक","मुद्दा दोन","मुद्दा तीन"], "kind": "concept", "chips": ["कीवर्ड"]}],
                   "recap": "दोन-तीन वाक्यांचा मराठी सारांश.", "cta": "Subscribe करा आणि टेलिग्रामवर @mmindpower_1 मध्ये रोज सराव करा."}
        prompt = (f'Topic: "{topic}".\n'
                  f'Grounding from Wikipedia (optional reference):\n' + ground + '\n\n'
                  f'Write a ~5-minute Marathi explainer-video script. Respond with ONLY valid JSON — one object with keys '
                  f'exactly: title, hook, chapters (array of exactly {nsec}), recap, cta. Each chapter has keys: heading, '
                  f'narration, bullets, kind, chips.\n'
                  'STRUCTURE EXAMPLE (imitate EXACTLY, with real content):\n' + json.dumps(example, ensure_ascii=False) + '\n'
                  'Rules: (1) strings must be single-line — no raw line breaks inside them; (2) no trailing commas; '
                  '(3) no code fences, no commentary; narration = 55-85 words, spoken register; bullets <= 12 words; '
                  '(4) kind is one of concept/compare/steps/def.')
        try:
            txt = ""
            for mdl in ("openai/gpt-oss-120b", "meta-llama/llama-4-scout-17b-16e-instruct",
                        "qwen/qwen3-32b", "llama-3.1-8b-instant"):
                r = requests.post("https://api.groq.com/openai/v1/chat/completions",
                                  headers={"Authorization": f"Bearer {gk}"},
                                  json={"model": mdl, "temperature": 0.4,
                                        "messages": [{"role": "system", "content": "You are a Marathi educational scriptwriter. You output STRICT JSON only — valid, parseable, single-line strings."},
                                                     {"role": "user", "content": prompt}]},
                                  timeout=120)
                try:
                    txt = r.json()["choices"][0]["message"]["content"].strip()
                    say(f"groq ok via {mdl}")
                    break
                except Exception as e:
                    say(f"groq[{mdl}] fail:", str(r.json())[:110] if r.text else str(e))
                    txt = ""
            if not txt:
                raise ValueError("all groq models failed")
            m2 = re.search(r"\{.*\}", txt, re.S)
            if not m2:
                raise ValueError("no JSON in model reply: " + txt[:90])
            raw = m2.group(0)
            try:
                sc = json.loads(raw)
            except Exception as e1:
                sc = None
                # rescue 1: over-escaped structural quotes (\" where plain " belongs)
                if raw.count('\\"') >= 4:
                    try:
                        sc = json.loads(raw.replace('\\"', '"'))
                        say("groq json rescued via structural de-escape")
                    except Exception:
                        sc = None
                if sc is None:
                    try:
                        ctx = raw[max(0, e1.pos - 120): e1.pos + 120]
                        os.makedirs(OUT, exist_ok=True)
                        open(os.path.join(OUT, "groq_raw.txt"), "w").write(
                            "ERR " + str(e1) + "\n\n...AROUND...\n" + ctx + "\n\n...FULL...\n" + txt)
                        say("groq json err @" + str(e1.pos) + " ctx: " + ctx[:110].replace("\n", "\\n"))
                    except Exception:
                        pass
                    # rescue 2: trailing commas + smart quotes
                    healed = re.sub(r",\s*([}\]])", r"\1", raw)
                    healed = healed.replace("’", "'").replace("“", '"').replace("”", '"')
                    try:
                        sc = json.loads(healed)
                        say("groq json rescued via comma/quote healer")
                    except Exception:
                        # rescue 3: walk error positions, delete offending commas
                        for _ in range(10):
                            try:
                                sc = json.loads(healed)
                                say("groq json rescued via comma-walk")
                                break
                            except Exception as e3:
                                p = e3.pos
                                if healed[max(0, p - 1):p] == ",":
                                    healed = healed[:p - 1] + " " + healed[p:]
                                else:
                                    raise
            assert len(sc.get("chapters", [])) >= 3
            say(f"groq script OK — {len(sc['chapters'])} chapters")
            return sc
        except Exception as e:
            try:
                say("groq raw head: " + str(r.json())[:160])
            except Exception:
                pass
            say(f"groq script fail: {str(e)[:100]} — building fallback script")
    # fallback: wiki sentences as chapters
    paras = [p.strip() for p in re.split(r"(?<=[।.!?])\s+", ground) if len(p.strip()) > 40]
    while len(paras) < nsec: paras.append(topic + " — हा MPSC परीक्षेसाठी अत्यंत महत्त्वाचा विषय आहे, मुद्देसूद ठेवा.")
    chapters = []
    for i, p in enumerate(paras[:nsec]):
        words = p.split()
        chapters.append({"heading": " ".join(words[:6])[:42], "narration": p[:600],
                         "bullets": [" ".join(words[i:i+9]) for i in range(0, min(len(words), 45), 9)][:5],
                         "kind": "concept", "chips": [topic[:18]]})
    return {"title": topic, "hook": f"नमस्कार! Mmindpower मध्ये स्वागत. आज आपण सविस्तरपणे समजून घेणार आहोत — {topic}. सोप्या भाषेत, मुद्देसूद.", "chapters": chapters,
            "recap": f"आज आपण {topic} याबद्दलचे सारे महत्त्वाचे मुद्दे पाहिले. सातत्याने सराव करा.", "cta": "आवडल्यास Subscribe करा आणि टेलिग्रामवर @mmindpower_1 मध्ये रोज सराव करा."}


# ------------------ quiz bite from our own bank ------------------
def _norm_q(q):
    import ast
    qq = dict(q)
    o = qq.get("options")
    if isinstance(o, str):
        try: qq["options"] = list(ast.literal_eval(o))
        except Exception: qq["options"] = [x.strip() for x in o.strip("[]").split(",") if x.strip()]
    ci = qq.get("correct_index", 0)
    if isinstance(ci, str):
        ci = ci.strip()
        qq["correct_index"] = ord(ci) - 65 if ci.isalpha() else (int(ci) if ci.isdigit() else 0)
    return qq


def quiz_bite(topic, k=2):
    keys = [w for w in re.split(r"\s+", topic) if len(w) > 2]
    pool = []
    for fp in glob.glob(os.path.join(ROOT, "quiz_data_*.json")):
        for q in json.load(open(fp, encoding="utf-8")):
            if "|" in (q.get("q_marathi") or ""): continue
            if keys and any(kw in q.get("q_marathi", "") for kw in keys): pool.append(_norm_q(q))
    rnd = random.Random(topic)
    rnd.shuffle(pool)
    if len(pool) < k:
        allq = [_norm_q(q) for fp in glob.glob(os.path.join(ROOT, "quiz_data_*.json"))
                for q in json.load(open(fp, encoding="utf-8")) if "|" not in (q.get("q_marathi") or "")]
        rnd.shuffle(allq); pool += [q for q in allq if q not in pool]
    return pool[:k]


# ------------------ assembly ------------------
def segs_from(img, aud, out, zoom=True, bed=False, gain=1.6):
    dur = dur_of(aud) + (0.6 if bed else 0.5)
    say(f"  seg {os.path.basename(out)} dur={dur:.1f}s")
    if bed:
        filt = (f"[0:v]scale={W}:{H}[v];[1:a]aresample=48000,volume={gain}[vo];"
                f"[2:a]aresample=48000,volume=0.09,lowpass=f=600,atrim=0:{dur:.2f}[bd];[vo][bd]amix=inputs=2:duration=first[a]")
        run(["ffmpeg","-y","-loop","1","-t",f"{dur:.2f}","-i",img,"-i",aud,
             "-f","lavfi","-i",f"anoisesrc=color=brown:duration={int(dur)+1}",
             "-filter_complex",filt,"-map","[v]","-map","[a]","-t",f"{dur:.2f}","-c:v","libx264","-tune","stillimage","-b:v","700k","-maxrate","780k","-bufsize","1560k",
             "-c:a","aac","-b:a","96k","-pix_fmt","yuv420p","-r",str(FPS),out])
    else:
        z = f",zoompan=z='min(zoom+0.0007,1.12)':d={FPS*40}:fps={FPS}:s={W}x{H}" if zoom else ""
        filt = f"[0:v]scale={W}:{H}{z}[v];[1:a]aresample=48000,volume={gain}[a]"
        run(["ffmpeg","-y","-loop","1","-t",f"{dur:.2f}","-i",img,"-i",aud,
             "-filter_complex",filt,"-map","[v]","-map","[a]","-t",f"{dur:.2f}","-c:v","libx264","-tune","stillimage","-b:v","700k","-maxrate","780k","-bufsize","1560k",
             "-c:a","aac","-b:a","96k","-pix_fmt","yuv420p","-r",str(FPS),out])

def chime_seg(img, out, work, dur=1.4):
    cw = os.path.join(work, "chime.wav"); synth_chime(cw)
    filt = f"[0:v]scale={W}:{H}[v];[1:a]aresample=48000[a]"
    run(["ffmpeg","-y","-loop","1","-t",str(dur),"-i",img,"-i",cw,
         "-filter_complex",filt,"-map","[v]","-map","[a]","-t",str(dur),"-c:v","libx264","-tune","stillimage",
         "-c:a","aac","-b:a","128k","-pix_fmt","yuv420p","-r",str(FPS),out])
    os.remove(cw)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", default="महाराष्ट्राचे भूगोल")
    ap.add_argument("--voice", default="")
    ap.add_argument("--lang", default="hinglish", choices=["mr", "hinglish"], help="film language")
    ap.add_argument("--seed-file", default="", help="day_seed.json — modern-history question seed")
    ap.add_argument("--preview", action="store_true")      # 3 chapters, no quiz bite
    ap.add_argument("--script-cache", default="")
    ap.add_argument("--no-quiz", action="store_true")
    ap.add_argument("--style", default="", choices=["", "documentary"])
    ap.add_argument("--dialect", default="", choices=["", "kolhapuri"],
                    help="'kolhapuri' → narration in Kolhapuri vernacular Marathi")
    a = ap.parse_args()
    if a.style == "documentary":
        doc_render(a); return
    os.makedirs(OUT, exist_ok=True); work = os.path.join(OUT, "seg"); os.makedirs(work, exist_ok=True)
    cache = a.script_cache or os.path.join(OUT, "script.json")

    seed = None
    if a.seed_file and os.path.exists(a.seed_file):
        seed = json.load(open(a.seed_file, encoding="utf-8"))
        say("seed loaded: " + seed["question"][:70])
    if os.path.exists(cache):
        sc = json.load(open(cache)); say("script loaded from cache")
    else:
        ground = wiki_ground(a.topic)
        if seed:
            for hint in (seed.get("answer", ""), seed.get("subtopic", "")[:40], seed["question"][:40]):
                if ground: break
                g2 = wiki_ground(hint)
                if g2:
                    ground = g2; say("wiki grounded via seed hint '" + hint[:30] + "'")
            ground = (ground + "\n\nSEED MPSC QUESTION (Marathi): " + seed["question"]
                      + "\nCorrect: " + seed.get("answer", "") + " (" + seed.get("answer_letter", "") + ")"
                      + "\nExplanation: " + seed.get("explanation", ""))[:2400]
        sc = groq_script(a.topic, ground, 3 if a.preview else 6, dialect=a.dialect, lang=a.lang, seed=seed)
        sc["lang"] = a.lang
        if a.lang == "hinglish" and seed:
            ft = (sc.get("film_title") or "").strip()
            sc["title"] = ft or ("Daily History Byte: " + (seed.get("answer") or ""))
            say("film title (Hinglish): " + sc["title"][:70])
        json.dump(sc, open(cache, "w"), ensure_ascii=False, indent=2)
        say("script cached → " + cache)
    try:
        from groq2stage import dedupe_repeats, marathi_lint
        sc = dedupe_repeats(sc)
        if sc.get("_dedupe_dropped"):
            say("anti-repeat guard: dropped {} repeated sentence(s)/bullet(s)".format(sc["_dedupe_dropped"]))
        if a.lang == "hinglish":
            sc = marathi_lint(sc)
            if sc.get("_marathi_lint_dropped"):
                say("marathi QC: deleted {} leaky sentence(s) before render".format(sc["_marathi_lint_dropped"]))
    except Exception as de:
        say("dedupe/lint guard skipped: " + str(de)[:60])
    chapters = sc["chapters"]
    names = [c["heading"] for c in chapters]
    if a.preview or a.no_quiz:
        qz = []
    elif seed and a.lang == "hinglish":
        al = "ABCD".find((seed.get("answer_letter") or "A").strip().upper()[:1] or "A")
        q = {"q_marathi": seed["question"], "options": list(seed.get("options") or [])[:4],
             "correct_index": al if al >= 0 else 0, "explanation_marathi": seed.get("explanation", "")}
        from groq2stage import quiz_retry_translate
        tr = quiz_retry_translate(seed)
        if tr:
            q.update(tr); say("quiz-bite translated → Hinglish")
            qz = [q]
        else:
            say("quiz translate FAILED after retries — quiz section DELETED from film (no Marathi shown to students)")
            qz = []
    else:
        qz = quiz_bite(a.topic, 2)

    # ---- cards + audio tasks ----
    card_dir = os.path.join(work, "cards"); os.makedirs(card_dir, exist_ok=True)
    plan = []   # (image, audio_path, kind, zoom, bed)
    def card(name, img): p = os.path.join(card_dir, name + ".png"); img.save(p); return p
    chips = [(c.get("chips") or [a.topic[:16]])[0] for c in chapters][:4]

    plan.append((card("c_title", title_card(sc["title"], chips)), os.path.join(work, "v_hook.mp3"), "bed"))
    plan_tts = [(sc["hook"], os.path.join(work, "v_hook.mp3"))]
    CFG["lang"] = a.lang
    hi = (a.lang == "hinglish")
    if hi:
        KIND_LABELS.update({"concept": "CONCEPT", "compare": "COMPARE", "steps": "STEPS", "def": "DEFINITION"})
        FALLBACK_SIDES.clear(); FALLBACK_SIDES.extend(["Side 1", "Side 2"])
    plan.append((card("c_map", map_card(names)), os.path.join(work, "v_map.mp3"), "bed"))
    if hi:
        plan_tts.append(("Aaj ke is safar mein hum step by step samjhenge — " + ", ".join(names) + ". Ready ho jao!", os.path.join(work, "v_map.mp3")))
    else:
        plan_tts.append(("आजच्या प्रवासात आपण " + ", ".join(names) + " अशी टप्प्याटप्प्याने सगळे मुद्दे समजून घेणार आहोत.", os.path.join(work, "v_map.mp3")))
    for i, ch in enumerate(chapters):
        p1 = card(f"c_s{i}", section_card(i, names, ch["heading"], ch.get("kind", "concept"), ch.get("bullets", []), ch.get("chips", [])))
        plan.append((p1, os.path.join(work, f"v_s{i}.mp3"), "zoom"))
        plan_tts.append(((ch.get("narration") or "")[:1100], os.path.join(work, f"v_s{i}.mp3")))
    for i, q in enumerate(qz):
        plan.append((card(f"c_qz{i}", quiz_card(i, len(qz), q)), os.path.join(work, f"v_qz{i}.mp3"), "zoom"))
        hi_q = CFG["lang"] == "hinglish"
        qd = (q.get("q_hi") or q["q_marathi"]) if hi_q else q["q_marathi"]
        od = (q.get("options_hi") or q["options"]) if hi_q else q["options"]
        ed = ((q.get("explain_hi") or q.get("explanation_marathi")) or "") if hi_q else (q.get("explanation_marathi") or "")
        opts = " ".join(f"{'ABCD'[j]} — {o}." for j, o in enumerate(od[:4]))
        qline = (f"Ab quick quiz check! Sawaal: {qd} Options: {opts}" if hi_q
                 else f"थोडक्यात तपासूया. प्रश्न: {q['q_marathi']} पर्यायः {opts}")
        plan_tts.append((qline, os.path.join(work, f"v_qz{i}.mp3")))
        plan.append((card(f"c_za{i}", quiz_answer_card(i, len(qz), q)), os.path.join(work, f"v_za{i}.mp3"), "zoom"))
        ci = q.get("correct_index", 0)
        aline = (f"Sahi jawaab {'ABCD'[ci]} — {od[ci]}. {ed[:300]}" if hi_q
                 else f"योग्य उत्तर {'ABCD'[ci]} — {q['options'][ci]}. {(q.get('explanation_marathi') or '')[:300]}")
        plan_tts.append((aline, os.path.join(work, f"v_za{i}.mp3")))
    plan.append((card("c_recap", recap_card(sc["recap"])), os.path.join(work, "v_recap.mp3"), "bed"))
    plan_tts.append((sc["recap"], os.path.join(work, "v_recap.mp3")))
    plan.append((card("c_cta", cta_card(sc["cta"])), os.path.join(work, "v_cta.mp3"), "bed"))
    plan_tts.append((sc["cta"], os.path.join(work, "v_cta.mp3")))
    thumbnail(sc["title"], chips).save(os.path.join(OUT, "thumbnail.png")); say("thumbnail minted")

    import asyncio
    if resolve_voice(a.voice) is None:
        if a.lang == "hinglish":
            e_voice, e_pitch, e_rate = "hi-IN-SwaraNeural", "+0Hz", "+4%"   # Gen-Z Hindi female
            say("lang=hinglish → default voice hi-IN-SwaraNeural")
        else:
            e_voice, e_pitch, e_rate = "mr-IN-AarohiNeural", "+0Hz", "+4%"
            say("lang=mr → default voice mr-IN-AarohiNeural")
    else:
        e_voice, e_pitch, e_rate = resolve_voice(a.voice)
    asyncio.run(tts_all(plan_tts, e_voice, e_pitch, e_rate))

    # ---- assemble ----
    segs = []
    for idx, (img, aud, kind) in enumerate(plan):
        op = os.path.join(work, f"s{idx:02d}.mp4")
        if kind == "bed": segs_from(img, aud, op, zoom=False, bed=True)
        elif kind == "zoom": segs_from(img, aud, op, zoom=True)
        segs.append(op)
        if kind == "zoom":  # chapter chime divider after each content seg
            cp_ = os.path.join(work, f"ch{idx:02d}.mp4"); chime_seg(img, cp_, work); segs.append(cp_)
    lst = os.path.join(work, "list.txt")
    open(lst, "w").write("\n".join(f"file '{s}'" for s in segs))
    final = os.path.join(OUT, "final.mp4")
    run(["ffmpeg","-y","-f","concat","-safe","0","-i",lst,"-c","copy",final + ".tmp.mp4"])
    run(["ffmpeg","-y","-i",final + ".tmp.mp4","-c","copy","-movflags","+faststart",final])
    os.remove(final + ".tmp.mp4")

    # ---- skip-clips (concat-copy: seconds, no re-encode) + timestamps for buttons/caption ----
    intro_segs = segs[:2]                                    # title + map
    quiz_start = 2 + 2 * len(chapters)                       # each chapter = zoom + chime
    quiz_segs = segs[quiz_start: quiz_start + 4 * len(qz)]   # q-card + chime + a-card + chime per quiz
    intro_end_sec = round(sum(dur_of(s) for s in intro_segs))
    quiz_start_sec = round(sum(dur_of(s) for s in segs[:quiz_start]))
    def cat(seglist, outp):
        l2 = outp + ".list.txt"
        open(l2, "w").write("\n".join(f"file '{s}'" for s in seglist))
        run(["ffmpeg","-y","-f","concat","-safe","0","-i",l2,"-c","copy","-movflags","+faststart",outp])
    body_clip = quiz_clip = None
    if len(segs) > 2:
        body_clip = os.path.join(OUT, "final_body.mp4"); cat(segs[2:], body_clip)
        say("skip-intro clip → " + body_clip)
    if quiz_segs:
        quiz_clip = os.path.join(OUT, "final_quiz.mp4"); cat(quiz_segs, quiz_clip)
        say("jump-to-question clip → " + quiz_clip)
    total = sum(dur_of(s) for s in segs if s.endswith(".mp4"))
    meta = {"topic": sc["title"], "chapters": names, "quiz_bite": len(qz), "seconds": round(total),
            "intro_end_sec": intro_end_sec, "quiz_start_sec": quiz_start_sec,
            "minutes": round(total/60, 1), "bytes": os.path.getsize(final),
            "voice": a.voice or "(lang-default)", "lang": a.lang, "dialect": a.dialect or "std",
            "grounded_by": "wikipedia+groq", "date": datetime.datetime.now().isoformat(timespec="seconds")}
    json.dump(meta, open(os.path.join(OUT, "meta.json"), "w"), ensure_ascii=False, indent=2)
    say(f"DONE → {final} ({meta['bytes']//1024//1024}MB · {meta['minutes']} min)")


# ================= DOCUMENTARY LANE (narration-only · picture-led · 7 min) =================
def _dl(u, path, minb=3000):
    import requests as _rq
    b = _rq.get(u, timeout=30, headers={"User-Agent": "MmindpowerEdu/1.0 (educational documentary)"}).content
    if len(b) > minb:
        open(path, "wb").write(b)
        return path
    return None


def comm_img(query, path, width=1600):
    """Archival visual from Wikimedia Commons / Wikipedia (free-license). None on failure.
    Runner-safe: retries + endpoint fallbacks."""
    import requests as _rq
    UA = {"User-Agent": "MmindpowerEdu/1.0 (educational documentary film; contact: telegram @mmindpower_1)"}
    for attempt in range(3):                       # Commons search API, backoff
        try:
            r = _rq.get("https://commons.wikimedia.org/w/api.php", params={
                "action": "query", "format": "json", "generator": "search",
                "gsrsearch": query, "gsrnamespace": "6", "gsrlimit": "6",
                "prop": "imageinfo", "iiprop": "url", "iiurlwidth": str(width)},
                headers=UA, timeout=30)
            pages = r.json().get("query", {}).get("pages", {})
            for p in sorted(pages.values(), key=lambda x: x.get("index", 99)):
                ii = p.get("imageinfo") or []
                if ii and ii[0].get("thumburl"):
                    u = ii[0]["thumburl"]
                    if u.lower().split("?")[0].endswith((".jpg", ".jpeg", ".png")):
                        if _dl(u, path):
                            time.sleep(1.2)
                            say("archival image ok (commons): " + query[:40])
                            return path
            break
        except Exception as e:
            if attempt == 2:
                say("commons fetch fail (%s): %s" % (query[:30], str(e)[:60]))
            time.sleep(3 + 3 * attempt)
    # fallback: English Wikipedia page images
    try:
        t = query.strip()
        r = _rq.get("https://en.wikipedia.org/w/api.php", params={
            "action": "query", "format": "json", "generator": "search",
            "gsrsearch": t, "gsrlimit": "3", "prop": "pageimages", "pithumbsize": str(width)},
            headers=UA, timeout=25)
        pages = r.json().get("query", {}).get("pages", {})
        for p in sorted(pages.values(), key=lambda x: x.get("index", 99)):
            th = p.get("thumbnail", {})
            if th.get("source") and th["source"].lower().split("?")[0].endswith((".jpg", ".jpeg", ".png")):
                if _dl(th["source"], path):
                    time.sleep(1.2)
                    say("archival image ok (en.wiki): " + query[:40])
                    return path
    except Exception as e:
        say("wiki pageimage fail (%s): %s" % (query[:30], str(e)[:60]))
    return None


def doc_card(chip, heading, path):
    """Fallback visual: cinematic gradient + big wordmark (text only as last resort)."""
    img = bg((38, 26, 10)); d = ImageDraw.Draw(img)
    d.text((W // 2, H // 2 - 40), heading[:28], font=font(120), fill=(232, 197, 90), anchor="mm")
    d.text((W // 2, H // 2 + 90), chip[:26], font=font(52), fill=(230, 230, 230), anchor="mm")
    img.save(path)
    return path


def doc_frame(src_img, chip, idx, out):
    """Full-bleed picture + minimal caption band (pictures instead of text)."""
    from PIL import ImageFilter
    try:
        im = Image.open(src_img).convert("RGB")
    except Exception:
        return doc_card(chip, "Chapter " + str(idx + 1), out)
    r = max(W / im.width, H / im.height)
    im = im.resize((int(im.width * r), int(im.height * r)))
    x, y = (im.width - W) // 2, (im.height - H) // 2
    im = im.crop((x, y, x + W, y + H))
    band = Image.new("RGBA", (W, 150), (8, 8, 8, 165))
    layer = im.convert("RGBA"); layer.paste(band, (0, H - 150), band)
    d = ImageDraw.Draw(layer)
    d.text((46, H - 108), chip[:22], font=font(58), fill=(240, 233, 215))
    d.text((W - 46, H - 96), str(idx + 1), font=font(58), fill=(232, 197, 90), anchor="ra")
    layer.convert("RGB").save(out, quality=92)
    return out


def doc_fallback(seed, topic):
    """Zero-LLM documentary script from seed facts (statements only)."""
    q = seed or {}
    sub = (q.get("subtopic") or topic).strip()
    expl = (q.get("explanation") or "").strip()
    ans = (q.get("answer") or "").strip()
    sents = [x.strip() for x in expl.replace("?", "।").split("।") if len(x.strip()) > 8]
    arcs = [("Kahani ki Shuruaat", sub + " history", "background"),
            ("Nayak ka Parichay", sub + " portrait", "hero"),
            ("Pehla Mod", sub + " monument", "turning point"),
            ("Ran-neeti", sub + " map old", "strategy"),
            ("Climax ka Scene", sub + " painting battle", "climax"),
            ("Nateeja", sub + " memorial", "result"),
            ("Legacy — Aaj ka Sandesh", sub + " statue", "legacy")]
    chs = []
    for i, (h, iq, chip) in enumerate(arcs):
        core = (sents[i % len(sents)] + "। " + sents[(i + 1) % len(sents)] + "।") if sents else ""
        narr = (core + " Exam point of view: sahi tathya hai — " + ans + "।").strip()
        chs.append({"heading": h, "imgq": iq, "chip": chip, "narration": narr})
    return {"title": "Documentary: " + sub, "film_title": "Documentary: " + sub,
            "cold": "Ye kahani hai " + sub + " ki — jo itihaas ke panne mein likhi gayi, par aaj bhi exam ke sawaal mein zinda hai.",
            "chapters": chs, "outro": (sents[-1] + "। " if sents else "") + "Ye thi is episode ki asli kahani।",
            "cta": "Mmindpower ko Subscribe karo — Telegram @mmindpower_1 pe roz aisi hi ek documentary.",
            "lang": "hinglish", "style": "documentary", "_fallback": True}


# ---- Phase A: grade, stamp, montage, music ----
def grade_docgy(im):
    """Warm sepia grade + vignette — unifies mixed archival sources."""
    from PIL import ImageEnhance, ImageDraw as _D
    w, h = im.size
    r0, g0, b0 = im.split()
    sep = Image.merge("RGB", (
        r0.point(lambda i: min(255, i * 1.18)),
        g0.point(lambda i: min(255, i * 0.96)),
        b0.point(lambda i: i * 0.78)))
    sep = ImageEnhance.Color(sep).enhance(0.82)
    import math
    mask = Image.new("L", (w, h), 0)
    d = _D.Draw(mask)
    d.ellipse((-w * 0.25, -h * 0.3, w * 1.25, h * 1.3), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(120))
    dark = Image.new("RGB", (w, h), (10, 8, 6))
    return Image.composite(sep, dark, mask)


def doc_frame(src_img, chip, idx, out, stamp=""):
    """Full-bleed graded picture + caption band + RED circular year·place stamp (bottom-right)."""
    from PIL import ImageFilter, ImageDraw
    im = Image.open(src_img).convert("RGB")
    rr = max(W / im.width, H / im.height)
    im = im.resize((int(im.width * rr), int(im.height * rr)))
    x, y = (im.width - W) // 2, (im.height - H) // 2
    im = im.crop((x, y, x + W, y + H))
    im = grade_docgy(im)
    band = Image.new("RGBA", (W, 150), (8, 8, 8, 165))
    layer = im.convert("RGBA"); layer.paste(band, (0, H - 150), band)
    d = ImageDraw.Draw(layer)
    d.text((46, H - 108), chip[:22], font=font(58), fill=(240, 233, 215))
    d.text((46, H - 40), "#1857 documentary series", font=font(30), fill=(190, 185, 170))
    if stamp:
        Rr = 118; cx, cy = W - 200, H - 150 - Rr - 36
        d.ellipse((cx - Rr, cy - Rr, cx + Rr, cy + Rr), outline=(215, 44, 38), width=10,
                  fill=(150, 18, 14))
        parts = stamp.split("|")
        ln1, ln2 = (parts[0].strip()[:12], parts[1].strip()[:14] if len(parts) > 1 else "")
        d.text((cx, cy - 30), ln1, font=font(52), fill=(255, 235, 210), anchor="mm")
        if ln2:
            d.text((cx, cy + 34), ln2, font=font(40), fill=(255, 220, 200), anchor="mm")
    layer.convert("RGB").save(out, quality=92)
    return out


def frame_variants(paths, work, tag, target=15):
    """From fetched images, build `target` frames via crops (center/left/right/top/bottom)."""
    outs = []
    crops = [lambda w, h: (0, 0, w, h)]
    crops += [lambda w, h: (int(w*0.08), 0, w, h), lambda w, h: (0, int(h*0.08), w, h),
              lambda w, h: (int(w*0.14), int(h*0.14), w, h), lambda w, h: (0, 0, int(w*0.86), int(h*0.86))]
    for pi, p in enumerate(paths):
        try:
            im0 = Image.open(p).convert("RGB")
        except Exception:
            continue
        for ci, cf in enumerate(crops):
            try:
                box = cf(im0.width, im0.height)
                im0.crop(box).save(os.path.join(work, f"{tag}_f{pi:02d}_{ci}.png"), quality=90)
            except Exception:
                pass
    import glob as _g
    outs = sorted(_g.glob(os.path.join(work, f"{tag}_f*.png")))
    while len(outs) < target and outs:        # reuse w/ zoom-rotate until target
        srcp = outs[len(outs) % len(outs)]
        im = Image.open(srcp).convert("RGB").rotate((len(outs) % 3 - 1) * 1.5, expand=False)
        np_ = os.path.join(work, f"{tag}_fx{len(outs):02d}.png"); im.save(np_)
        outs.append(np_)
    return outs[:target]


def montage_chapter(frames_len, aud, work, out):
    """Chapter video = N frames switching every dur/N sec with soft fades; audio muxed."""
    import glob as _g
    frames = sorted(frames_len)
    if not frames:
        return None
    dur = dur_of(aud) + 0.35
    per = max(dur / len(frames), 2.5)
    segs = []
    for fi, fp in enumerate(frames):
        seg = os.path.join(work, f"m{os.path.basename(out)}_{fi:02d}.mp4")
        fade = (f"scale={W}:{H},zoompan=z='min(zoom+0.001,1.15)':d={int(per*FPS)+2}:fps={FPS}:s={W}x{H},"
                f"fade=t=in:st=0:d=0.25,fade=t=out:st={per-0.25:.2f}:d=0.25")
        run(["ffmpeg", "-y", "-loop", "1", "-t", f"{per:.2f}", "-i", fp,
             "-filter:v", fade, "-an", "-t", f"{per:.2f}", "-c:v", "libx264", "-tune", "stillimage",
             "-b:v", "700k", "-maxrate", "780k", "-bufsize", "1560k",
             "-pix_fmt", "yuv420p", "-r", str(FPS), seg])
        segs.append(seg)
    lst = os.path.join(work, "mlist.txt")
    open(lst, "w").write("\n".join(f"file '{x}'" for x in segs))
    mv = os.path.join(work, "m_" + os.path.basename(out))
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", mv])
    run(["ffmpeg", "-y", "-i", mv, "-i", aud, "-map", "0:v", "-map", "1:a",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "96k", "-shortest", out])
    return out


def mix_music(final, total):
    """Bed music under narration + loudness normalize. Music: assets/music/doc_bed.mp3 (CC-BY Sascha Ende)."""
    bed = os.path.join(ROOT, "assets", "music", "doc_bed.mp3")
    if not os.path.exists(bed):
        say("music bed missing — skipping bed mix")
        return
    tmp = final + ".mx.mp4"
    filt = ("[1:a]volume=0.075,lowpass=f=900[bed];"
            "[0:a][bed]amix=inputs=2:duration=first[m];[m]loudnorm=I=-16:TP=-1.5:LRA=11[a]")
    import subprocess as _sp
    p = _sp.run(["ffmpeg", "-y", "-i", final, "-stream_loop", "-1", "-i", bed, "-filter_complex", filt,
                 "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "112k",
                 "-movflags", "+faststart", tmp], capture_output=True)
    if p.returncode != 0:
        say("music mix ffmpeg warn: " + p.stderr.decode(errors="ignore")[-160:])
    if os.path.exists(tmp) and os.path.getsize(tmp) > 5000:
        os.replace(tmp, final)
        say("music bed mixed + loudness normalized")
    else:
        say("music mix skipped (output invalid) — narration-only final kept")


def mix_bed_on(aud_mp3, out_mp3):
    """Music bed under one narration file + light loudnorm. Falls back to raw copy."""
    import subprocess as _sp
    bed = os.path.join(ROOT, "assets", "music", "doc_bed.mp3")
    if not os.path.exists(bed):
        try:
            import shutil; shutil.copy(aud_mp3, out_mp3)
        except Exception:
            pass
        return out_mp3
    filt = ("[0:a]aresample=48000,volume=1.5[v];"
            "[1:a]aresample=48000,volume=0.075,lowpass=f=900[bed];"
            "[v][bed]amix=inputs=2:duration=first[m];[m]loudnorm=I=-17:TP=-1.5:LRA=12[a]")
    p = _sp.run(["ffmpeg", "-y", "-i", aud_mp3, "-stream_loop", "-1", "-i", bed,
                 "-filter_complex", filt, "-map", "[a]", "-c:a", "libmp3lame", "-b:a", "112k", out_mp3],
                capture_output=True)
    if p.returncode != 0 or not os.path.exists(out_mp3) or os.path.getsize(out_mp3) < 2000:
        import shutil; shutil.copy(aud_mp3, out_mp3)
        say("bed mix fallback for " + os.path.basename(aud_mp3))
    return out_mp3


def comm_imgs(query, work, tag, k=8):
    """Return up to k downloaded archival images (Commons first, en.wiki fallback)."""
    import requests as _rq
    UA = {"User-Agent": "MmindpowerEdu/1.0 (educational documentary film; contact: telegram @mmindpower_1)"}
    out = []
    def grab(pages):
        added = 0
        for p in sorted(pages.values(), key=lambda x: x.get("index", 99)):
            ii = p.get("imageinfo") or []
            u = None
            if ii and ii[0].get("thumburl") and ii[0]["thumburl"].lower().split("?")[0].endswith((".jpg", ".jpeg", ".png")):
                u = ii[0]["thumburl"]
            elif p.get("thumbnail", {}).get("source", "").lower().split("?")[0].endswith((".jpg", ".jpeg", ".png")):
                u = p["thumbnail"]["source"]
            if u:
                fp = os.path.join(work, f"{tag}_src{len(out):02d}.img")
                try:
                    import urllib.request as _ul
                    req = _ul.Request(u, headers=UA)
                    b = _ul.urlopen(req, timeout=30).read()
                    if len(b) > 4000:
                        open(fp, "wb").write(b)
                        out.append(fp); added += 1; time.sleep(0.8)
                except Exception:
                    pass
        return added
    for attempt in range(3):
        try:
            r = _rq.get("https://commons.wikimedia.org/w/api.php", params={
                "action": "query", "format": "json", "generator": "search",
                "gsrsearch": query, "gsrnamespace": "6", "gsrlimit": str(k),
                "prop": "imageinfo", "iiprop": "url", "iiurlwidth": "1400"},
                headers=UA, timeout=30)
            grab((r.json().get("query") or {}).get("pages", {}))
            if out:
                break
        except Exception as e:
            time.sleep(2 + 2 * attempt)
    if len(out) < 2:
        try:
            r = _rq.get("https://en.wikipedia.org/w/api.php", params={
                "action": "query", "format": "json", "generator": "search",
                "gsrsearch": query, "gsrlimit": str(k), "prop": "pageimages", "pithumbsize": "1400"},
                headers=UA, timeout=25)
            grab((r.json().get("query") or {}).get("pages", {}))
        except Exception:
            pass
    say(f"chapter images [{tag}] fetched: {len(out)} ({query[:32]})")
    return out


def doc_render(a):
    seed = None
    if a.seed_file and os.path.exists(a.seed_file):
        seed = json.load(open(a.seed_file, encoding="utf-8"))
        say("doc seed loaded: " + seed["question"][:70])
    work = os.path.join(OUT, "seg"); os.makedirs(work, exist_ok=True)
    cache = a.script_cache or os.path.join(OUT, "script.json")
    if os.path.exists(cache):
        sc = json.load(open(cache)); say("doc script from cache")
    else:
        ground = wiki_ground(a.topic)
        if seed and not ground:
            for hint in (seed.get("answer", ""), seed.get("subtopic", "")[:40]):
                g2 = wiki_ground(hint)
                if g2:
                    ground = g2; break
        from groq2stage import groq_doc_script
        sc = groq_doc_script(a.topic, ground, 7, seed=seed, outdir=work)
        if not sc:
            say("groq doc script unavailable → seed fallback script")
            sc = doc_fallback(seed, a.topic)
        from groq2stage import question_lint, marathi_lint, dedupe_repeats
        sc = question_lint(sc)
        sc = marathi_lint(sc)
        sc = dedupe_repeats(sc)
        if sc.get("_questions_dropped"):
            say("zero-question QC: dropped %d question line(s)" % sc["_questions_dropped"])
        if sc.get("_marathi_lint_dropped"):
            say("marathi QC: deleted %d leaky line(s)" % sc["_marathi_lint_dropped"])
        if sc.get("_dedupe_dropped"):
            say("anti-repeat: dropped %d" % sc["_dedupe_dropped"])
        json.dump(sc, open(cache, "w"), ensure_ascii=False, indent=2)
        say("doc script cached → " + cache)
    chapters = sc["chapters"]
    ch_frames = []
    for i, ch in enumerate(chapters):
        paths = comm_imgs(ch.get("imgq") or a.topic, work, f"c{i}")
        if not paths:
            paths = [doc_card(ch.get("chip", ""), ch.get("heading", ""), os.path.join(work, f"c{i}_fb.png"))]
        variants = frame_variants(paths, work, f"c{i}v", target=15)
        frames = []
        for fi, v in enumerate(variants):
            fp = doc_frame(v, ch.get("chip", ""), i, os.path.join(work, f"c{i}_g{fi:02d}.png"),
                           stamp=ch.get("stamp", ""))
            frames.append(fp)
        ch_frames.append(frames)
        say(f"chapter {i+1}: {len(frames)} frames graded")
    if resolve_voice(a.voice) is None:
        e_voice, e_pitch, e_rate = "hi-IN-SwaraNeural", "+0Hz", "+3%"
    else:
        e_voice, e_pitch, e_rate = resolve_voice(a.voice)
    tasks, plan = [], []
    cold_aud = os.path.join(work, "n_cold.mp3")
    tasks.append((sc.get("cold", sc["title"]), cold_aud)); plan.append(("single", ch_frames[0][0], cold_aud))
    for i, ch in enumerate(chapters):
        au = os.path.join(work, f"n_ch{i}.mp3")
        tasks.append((ch.get("narration", "")[:1500], au)); plan.append(("montage", ch_frames[i], au))
    out_aud = os.path.join(work, "n_out.mp3")
    tasks.append(((sc.get("outro", "") + " Background score: Epic Drone Shots by Sascha Ende (CC-BY 4.0) via Wikimedia Commons. " + sc.get("cta", "")).strip(), out_aud))
    plan.append(("single", ch_frames[-1][0], out_aud))
    import asyncio
    asyncio.run(tts_all(tasks, e_voice, e_pitch, e_rate))
    segs = []
    for idx, (kind, img, aud) in enumerate(plan):
        mx = os.path.join(work, f"d{idx:02d}_mx.mp3")
        mix_bed_on(aud, mx)
        op = os.path.join(work, f"d{idx:02d}.mp4")
        if kind == "montage":
            montage_chapter(img, mx, work, op)
        else:
            segs_from(img, mx, op, zoom=True, gain=1.0)
        segs.append(op)
    lst = os.path.join(work, "dlist.txt")
    open(lst, "w").write("\n".join(f"file '{x}'" for x in segs))
    final = os.path.join(OUT, "final.mp4")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", final + ".tmp.mp4"])
    run(["ffmpeg", "-y", "-i", final + ".tmp.mp4", "-c", "copy", "-movflags", "+faststart", final])
    os.remove(final + ".tmp.mp4")
    total = sum(dur_of(x) for x in segs if x.endswith(".mp4"))
    if os.path.getsize(final) > 46 * 1024 * 1024:
        say("final >46MB → safety re-encode @520k")
        run(["ffmpeg", "-y", "-i", final, "-c:v", "libx264", "-b:v", "520k", "-maxrate", "620k",
             "-bufsize", "1240k", "-c:a", "aac", "-b:a", "80k", "-movflags", "+faststart", final + ".sm.mp4"])
        os.replace(final + ".sm.mp4", final)
    chips = [(c.get("chip") or c.get("heading", "")) for c in chapters][:4]
    thumbnail(sc["title"], chips).save(os.path.join(OUT, "thumbnail.png"))
    meta = {"topic": sc["title"], "style": "documentary", "chapters": [c["heading"] for c in chapters],
            "quiz_bite": 0, "seconds": round(total), "minutes": round(total / 60, 1),
            "bytes": os.path.getsize(final), "lang": a.lang, "voice": e_voice,
            "frames_per_chapter": 15, "music": "Epic Drone Shots — Sascha Ende (CC-BY 4.0)",
            "date": datetime.datetime.now().isoformat(timespec="seconds")}
    json.dump(meta, open(os.path.join(OUT, "meta.json"), "w"), ensure_ascii=False, indent=2)
    say(f"DOC DONE → {final} ({meta['bytes']//1024//1024}MB · {meta['minutes']} min · {len(chapters)} sub-topics · 15 frames/ch)")


if __name__ == "__main__":
    main()
