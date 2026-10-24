#!/usr/bin/env python3
"""Mmindpower Explainer Wing — a topic in -> a ~5-min branded Marathi explainer video out.
Pipeline: Wikipedia(-mr, free) grounding -> Groq composes a chaptered script (strict JSON)
-> PIL cinema cards (concept/def/compare/steps/quiz-bite kinds) -> neural TTS -> ffmpeg assembly.
Usage: python3 tools/video_explainer.py --topic "..." [--voice mr-IN-ManoharNeural] [--preview] [--script-cache out_explainer/script.json]
"""
import os, sys, json, glob, random, subprocess, argparse, time, datetime, re

from PIL import Image, ImageDraw, ImageFont, ImageFilter

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
        o = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",path],
                           capture_output=True, text=True, timeout=30)
        return float(o.stdout.strip())
    except Exception:
        return default


# ------------------ PIL cinema engine ------------------
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
    d.text((W//2, 190), "आजची शिखर-यात्रा", font=font(96), fill=GOLD, anchor="mm")
    y = 330
    for i, c in enumerate(chapters):
        d.rounded_rectangle((270, y, 390, y+70), 14, fill=(24, 48, 98), outline=GOLD, width=3)
        d.text((330, y+35), str(i+1), font=font(44), fill=GOLD, anchor="mm")
        d.text((440, y+17), c, font=fit(d, c, 1200, 50), fill=WHITE)
        y += 96
    return chrome(img, chapters=chapters)

def section_card(idx, chapters, heading, kind, bullets, chips):
    img = bg(); d = ImageDraw.Draw(img)
    kind_icon = {"concept": "संकल्पना", "compare": "तुलना", "steps": "पायऱ्या", "def": "व्याख्या"}.get(kind, "संकल्पना")
    d.text((W//2, 180), heading, font=fit(d, heading, 1500, 72, 42), fill=GOLD, anchor="mm")
    d.text((170, 165), kind_icon, font=fit(d, kind_icon, 300, 46, 30), fill=CYAN)
    if kind == "compare" and len(bullets) >= 2:
        halves = [bullets[:len(bullets)//2] or bullets[:1], bullets[len(bullets)//2:]]
        labels = chips[:2] if len(chips) >= 2 else ["बाजू १", "बाजू २"]
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
    img = bg((10, 44, 40)); d = ImageDraw.Draw(img)
    d.text((W//2, 170), "✦ जलद तपासणी ✦", font=font(80), fill=GREEN, anchor="mm")
    y = 290
    for ln in wrap(d, q["q_marathi"], font(50), 1560)[:3]:
        d.text((170, y), ln, font=font(50), fill=WHITE); y += 76
    y += 16
    for jnn, opt in enumerate(q["options"][:4]):
        d.text((230, y), f"{'ABCD'[jnn]})", font=font(44), fill=GOLD)
        d.text((330, y), str(opt)[:80], font=fit(d, str(opt), 1350, 44, 32), fill=WHITE); y += 82
    d.text((W//2, H-170), "उत्तरही लगेचच — पाहत राहा!", font=font(44), fill=MUTE, anchor="mm")
    return chrome(img, f"quiz {i+1}/{n}")

def quiz_answer_card(i, n, q):
    img = bg((10, 44, 40)); d = ImageDraw.Draw(img)
    ci = q.get("correct_index", 0)
    d.text((W//2, 200), f"उत्तर: {'ABCD'[ci]}", font=font(96), fill=GREEN, anchor="mm")
    d.text((W//2, 330), str(q["options"][ci])[:100], font=fit(d, str(q["options"][ci]), 1500, 52), fill=WHITE, anchor="mm")
    y = 470
    for ln in wrap(d, (q.get("explanation_marathi") or "")[:400], font(46), 1500)[:5]:
        d.text((160, y), ln, font=font(46), fill=WHITE); y += 70
    return chrome(img, f"quiz {i+1}/{n}")

def recap_card(recap):
    img = bg(); d = ImageDraw.Draw(img)
    d.text((W//2, 200), "✦ एका नजरेत ✦", font=font(92), fill=GOLD, anchor="mm")
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

async def tts_all(tasks, voice):
    try:
        import edge_tts; edge_ok = True
    except Exception:
        edge_ok = False
    for text, path in tasks:
        os.makedirs(os.path.dirname(path), exist_ok=True); done = False
        if edge_ok:
            try:
                import asyncio as _a
                comm = edge_tts.Communicate(text=text[:1800], voice=voice, rate="+6%")
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

def groq_script(topic, ground, nsec):
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
        prompt = (f'Topic: "{topic}".\n'
                  f'Grounding from Wikipedia (may be partial, trust only what is here or is common knowledge):\n{ground}\n\n'
                  f'Compose a 5-minute Marathi explainer video script as STRICT JSON following this schema EXACTLY '
                  f'(keys exactly as named, chapters array of exactly {nsec} items):\n{json.dumps(schema, ensure_ascii=False)}\n'
                  'Rules: narration must flow when spoken aloud; bullets are on-screen support (concise, no emojis); '
                  'Use Devanagari digits sparingly. Output JSON only, no fences.')
        try:
            r = requests.post("https://api.groq.com/openai/v1/chat/completions",
                              headers={"Authorization": f"Bearer {gk}"},
                              json={"model": "openai/gpt-oss-120b", "temperature": 0.65,
                                    "messages": [{"role": "system", "content": "You are a Marathi educational scriptwriter. Output valid JSON only."},
                                                 {"role": "user", "content": prompt}]},
                              timeout=90)
            txt = r.json()["choices"][0]["message"]["content"].strip()
            m2 = re.search(r"\{.*\}", txt, re.S)   # forgive fences/prose: rescue the JSON island
            if not m2:
                raise ValueError("no JSON in model reply: " + txt[:90])
            sc = json.loads(m2.group(0))
            assert len(sc.get("chapters", [])) >= 3
            say(f"groq script OK — {len(sc['chapters'])} chapters")
            return sc
        except Exception as e:
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
def quiz_bite(topic, k=2):
    keys = [w for w in re.split(r"\s+", topic) if len(w) > 2]
    pool = []
    for fp in glob.glob(os.path.join(ROOT, "quiz_data_*.json")):
        for q in json.load(open(fp, encoding="utf-8")):
            if "|" in (q.get("q_marathi") or ""): continue
            if keys and any(kw in q.get("q_marathi", "") for kw in keys): pool.append(q)
    rnd = random.Random(topic)
    rnd.shuffle(pool)
    if len(pool) < k:
        allq = [q for fp in glob.glob(os.path.join(ROOT, "quiz_data_*.json"))
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
             "-filter_complex",filt,"-map","[v]","-map","[a]","-t",f"{dur:.2f}","-c:v","libx264","-tune","stillimage",
             "-c:a","aac","-b:a","128k","-pix_fmt","yuv420p","-r",str(FPS),out])
    else:
        z = f",zoompan=z='min(zoom+0.0007,1.12)':d={FPS*40}:fps={FPS}:s={W}x{H}" if zoom else ""
        filt = f"[0:v]scale={W}:{H}{z}[v];[1:a]aresample=48000,volume={gain}[a]"
        run(["ffmpeg","-y","-loop","1","-t",f"{dur:.2f}","-i",img,"-i",aud,
             "-filter_complex",filt,"-map","[v]","-map","[a]","-t",f"{dur:.2f}","-c:v","libx264","-tune","stillimage",
             "-c:a","aac","-b:a","128k","-pix_fmt","yuv420p","-r",str(FPS),out])

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
    ap.add_argument("--voice", default="mr-IN-ManoharNeural")
    ap.add_argument("--preview", action="store_true")      # 3 chapters, no quiz bite
    ap.add_argument("--script-cache", default="")
    ap.add_argument("--no-quiz", action="store_true")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True); work = os.path.join(OUT, "seg"); os.makedirs(work, exist_ok=True)
    cache = a.script_cache or os.path.join(OUT, "script.json")

    if os.path.exists(cache):
        sc = json.load(open(cache)); say("script loaded from cache")
    else:
        ground = wiki_ground(a.topic)
        sc = groq_script(a.topic, ground, 3 if a.preview else 6)
        json.dump(sc, open(cache, "w"), ensure_ascii=False, indent=2)
        say("script cached → " + cache)
    chapters = sc["chapters"]
    names = [c["heading"] for c in chapters]
    qz = [] if (a.preview or a.no_quiz) else quiz_bite(a.topic, 2)

    # ---- cards + audio tasks ----
    card_dir = os.path.join(work, "cards"); os.makedirs(card_dir, exist_ok=True)
    plan = []   # (image, audio_path, kind, zoom, bed)
    def card(name, img): p = os.path.join(card_dir, name + ".png"); img.save(p); return p
    chips = [(c.get("chips") or [a.topic[:16]])[0] for c in chapters][:4]

    plan.append((card("c_title", title_card(sc["title"], chips)), os.path.join(work, "v_hook.mp3"), "bed"))
    plan_tts = [(sc["hook"], os.path.join(work, "v_hook.mp3"))]
    plan.append((card("c_map", map_card(names)), os.path.join(work, "v_map.mp3"), "bed"))
    plan_tts.append(("आजच्या प्रवासात आपण " + ", ".join(names) + " अशी टप्प्याटप्प्याने सगळे मुद्दे समजून घेणार आहोत.", os.path.join(work, "v_map.mp3")))
    for i, ch in enumerate(chapters):
        p1 = card(f"c_s{i}", section_card(i, names, ch["heading"], ch.get("kind", "concept"), ch.get("bullets", []), ch.get("chips", [])))
        plan.append((p1, os.path.join(work, f"v_s{i}.mp3"), "zoom"))
        plan_tts.append(((ch.get("narration") or "")[:1100], os.path.join(work, f"v_s{i}.mp3")))
    for i, q in enumerate(qz):
        plan.append((card(f"c_qz{i}", quiz_card(i, len(qz), q)), os.path.join(work, f"v_qz{i}.mp3"), "zoom"))
        opts = " ".join(f"{'ABCD'[j]} — {o}." for j, o in enumerate(q["options"][:4]))
        plan_tts.append((f"थोडक्यात तपासूया. प्रश्न: {q['q_marathi']} पर्यायः {opts}", os.path.join(work, f"v_qz{i}.mp3")))
        plan.append((card(f"c_za{i}", quiz_answer_card(i, len(qz), q)), os.path.join(work, f"v_za{i}.mp3"), "zoom"))
        ci = q.get("correct_index", 0)
        plan_tts.append((f"योग्य उत्तर {'ABCD'[ci]} — {q['options'][ci]}. {(q.get('explanation_marathi') or '')[:300]}", os.path.join(work, f"v_za{i}.mp3")))
    plan.append((card("c_recap", recap_card(sc["recap"])), os.path.join(work, "v_recap.mp3"), "bed"))
    plan_tts.append((sc["recap"], os.path.join(work, "v_recap.mp3")))
    plan.append((card("c_cta", cta_card(sc["cta"])), os.path.join(work, "v_cta.mp3"), "bed"))
    plan_tts.append((sc["cta"], os.path.join(work, "v_cta.mp3")))
    thumbnail(sc["title"], chips).save(os.path.join(OUT, "thumbnail.png")); say("thumbnail minted")

    import asyncio
    asyncio.run(tts_all(plan_tts, a.voice))

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
    total = sum(dur_of(s) for s in segs if s.endswith(".mp4"))
    meta = {"topic": sc["title"], "chapters": names, "quiz_bite": len(qz), "seconds": round(total),
            "minutes": round(total/60, 1), "bytes": os.path.getsize(final),
            "grounded_by": "wikipedia+groq", "date": datetime.datetime.now().isoformat(timespec="seconds")}
    json.dump(meta, open(os.path.join(OUT, "meta.json"), "w"), ensure_ascii=False, indent=2)
    say(f"DONE → {final} ({meta['bytes']//1024//1024}MB · {meta['minutes']} min)")


if __name__ == "__main__":
    main()
