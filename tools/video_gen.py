#!/usr/bin/env python3
"""Mmindpower Video Factory — a topic/set in -> a branded ~5-min quiz video out.
Runs on GitHub Actions. Free stack only: own Q-bank + PIL cards + Edge-TTS neural (Marathi) + ffmpeg.
Usage: python3 tools/video_gen.py --topic "..." [--set A] [--n 10] [--voice mr-IN-ManoharNeural] [--preview]
Outputs into out_video/: final.mp4, thumbnail.png, meta.json
"""
import os, sys, json, glob, random, subprocess, argparse, time, datetime

from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT_B = os.path.join(ROOT, "assets", "fonts", "NotoSansDevanagari-Bold.ttf")
OUT = os.path.abspath(os.path.join(ROOT, "out_video"))
W, H, FPS = 1920, 1080, 30
BRAND = "Mmindpower"
NAVY1, NAVY2 = (8, 18, 44), (22, 52, 110)
GOLD, GREEN, WHITE, MUTE = (255, 199, 95), (74, 222, 128), (246, 249, 255), (168, 186, 214)


def say(msg): print(time.strftime("[%H:%M:%S]"), msg, flush=True)
def run(cmd, **kw):
    say("ffmpeg: " + " ".join(cmd[:6]) + " …")
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, **kw)

def dur_of(path, default=2.0):
    try:
        o = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "csv=p=0", path], capture_output=True, text=True, timeout=30)
        return float(o.stdout.strip())
    except Exception:
        return default


# ------------------ PIL card engine ------------------
def bg(vignette=True):
    img = Image.new("RGB", (W, H), NAVY1)
    for y in range(H):  # vertical gradient
        t = y / H
        img.paste((int(NAVY1[0] + (NAVY2[0]-NAVY1[0])*t), int(NAVY1[1] + (NAVY2[1]-NAVY1[1])*t),
                   int(NAVY1[2] + (NAVY2[2]-NAVY1[2])*t)), (0, y, W, y+1))
    glow = Image.new("L", (W, H), 0)
    gd = ImageDraw.Draw(glow)
    gd.ellipse((W-560, -260, W+180, 300), fill=70)
    gd.ellipse((-320, H-420, 300, H+150), fill=45)
    glow = glow.filter(ImageFilter.GaussianBlur(120))
    base = Image.new("RGB", (W, H), GOLD)
    img.paste(base, (0, 0), glow)
    if vignette:
        v = Image.new("L", (W, H), 0)
        vd = ImageDraw.Draw(v); vd.rounded_rectangle((0, 0, W, H), 200, fill=110)
        black = Image.new("RGB", (W, H), (0, 0, 0))
        img.paste(black, (0, 0), Image.eval(v, lambda p: max(0, 110-p)))
    return img


def font(size): return ImageFont.truetype(FONT_B, size)

def fit(draw, text, maxw, start_size, min_size=34):
    s = start_size
    while s > min_size and draw.textlength(text, font=font(s)) > maxw: s -= 4
    return font(s)

def wrap(draw, text, fnt, maxw):
    words, lines, cur = text.split(), [], ""
    for wd in words:
        t = (cur + " " + wd).strip()
        if draw.textlength(t, font=fnt) <= maxw: cur = t
        else:
            lines.append(cur or wd); cur = "" if not cur else wd
    if cur: lines.append(cur)
    return lines

def header_footer(img, tag=""):
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, 12), fill=GOLD)
    d.text((70, H-68), BRAND + "  •  Daily Quiz", font=font(38), fill=MUTE)
    d.text((W-70, H-68), tag, font=font(38), fill=MUTE, anchor="ra")
    return img

def intro_card(topic, n):
    img = bg(); d = ImageDraw.Draw(img)
    d.text((W//2, 210), BRAND, font=font(96), fill=GOLD, anchor="mm")
    d.text((W//2, 300), "Daily Quiz • MPSC / Talathi", font=font(48), fill=MUTE, anchor="mm")
    big = fit(d, topic, 1500, 120)
    d.text((W//2, 560), topic, font=big, fill=WHITE, anchor="mm")
    d.rounded_rectangle((W//2-360, 730, W//2+360, 830), 40, outline=GOLD, width=6)
    d.text((W//2, 780), f"{n} प्रश्न • उत्तरे फक्त ५ सेकंदांत!", font=font(52), fill=GOLD, anchor="mm")
    return header_footer(img)

def stripes(d, i, n):
    x0 = (W - (n*34))//2
    for k in range(n):
        col = GOLD if k == i else (60, 82, 128)
        d.rounded_rectangle((x0 + k*34, 60, x0 + k*34 + 22, 72), 5, fill=col)

def question_card(i, n, q):
    img = bg(); d = ImageDraw.Draw(img)
    stripes(d, i, n)
    d.text((W//2, 150), f"प्रश्न {i+1} / {n}", font=font(68), fill=GOLD, anchor="mm")
    y = 240
    for ln in wrap(d, q["q_marathi"], font(60), 1600):
        d.text((160, y), ln, font=font(60), fill=WHITE); y += 88
    y += 30
    for j, opt in enumerate(q["options"][:4]):
        d.rounded_rectangle((150, y, W-150, y+92), 18, fill=(16, 34, 72), outline=(70, 100, 168))
        d.text((195, y+22), f"{'ABCD'[j]})", font=font(52), fill=GOLD)
        d.text((320, y+22), str(opt)[:90], font=fit(d, str(opt), W-560, 52), fill=WHITE)
        y += 112
    return header_footer(img, f"{i+1}/{n}")

def answer_card(i, n, q, expl):
    img = bg(); d = ImageDraw.Draw(img)
    stripes(d, i, n)
    ci = q.get("correct_index", 0)
    d.text((W//2, 140), f"उत्तर — {'ABCD'[ci]}", font=font(72), fill=GREEN, anchor="mm")
    # correct answer: wrapped to ≤2 lines inside a taller green box (long options never overflow)
    d.rounded_rectangle((150, 210, W-150, 390), 24, fill=(12, 60, 40), outline=GREEN, width=5)
    fy = 236
    ans_lines = wrap(d, str(q["options"][ci]), font(52), W-420)
    for ln in ans_lines[:2]:
        d.text((190, fy), ln, font=font(52), fill=WHITE); fy += 76
    if len(ans_lines) > 2:
        d.text((190, fy), "…", font=font(52), fill=WHITE)
    y = 450  # explanation: capped to 6 lines, guaranteed clear of the bottom prompt
    for ln in wrap(d, (expl or "").strip(), font(50), 1620)[:6]:
        d.text((160, y), ln, font=font(50), fill=WHITE); y += 72
    d.text((W//2, H-140), "तुमचे उत्तर बरोबर होते का?", font=font(48), fill=GOLD, anchor="mm")
    return header_footer(img, f"{i+1}/{n}")

def outro_card(cta):
    img = bg(); d = ImageDraw.Draw(img)
    d.text((W//2, 300), "Thank You!", font=font(120), fill=GOLD, anchor="mm")
    y = 430
    for ln in wrap(d, cta, font(58), 1500):
        d.text((W//2, y), ln, font=font(58), fill=WHITE, anchor="mm"); y += 86
    d.text((W//2, H-190), "YouTube: @mmindpower   •   Telegram: @mmindpower_1", font=font(46), fill=MUTE, anchor="mm")
    img2 = bg(vignette=False); d2 = ImageDraw.Draw(img2)
    d2.text((W//2, 430), "Mmindpower", font=font(150), fill=GOLD, anchor="mm")
    d2.text((W//2, 580), "रोजची टेस्ट. रोजची प्रगती.", font=font(58), fill=WHITE, anchor="mm")
    d2.rounded_rectangle((W//2-300, 700, W//2+300, 810), 40, fill=(200, 40, 40))
    d2.text((W//2, 755), "SUBSCRIBE", font=font(56), fill=WHITE, anchor="mm")
    return header_footer(img), img2

def thumbnail(topic):
    img = bg(vignette=False); d = ImageDraw.Draw(img)
    d.rectangle((0, H-260, W, H), fill=(0, 0, 0))
    d.text((W//2, 300), "Daily Quiz", font=font(100), fill=WHITE, anchor="mm")
    t = fit(d, topic, 1600, 130)
    d.text((W//2, 470), topic, font=t, fill=GOLD, anchor="mm")
    d.text((W//2, 640), "10 प्रश्न • 5 मिनिटे • MPSC/Talathi", font=font(56), fill=MUTE, anchor="mm")
    d.text((W//2, H-130), "Mmindpower", font=font(110), fill=GOLD, anchor="mm")
    return img


# ------------------ TTS voice ------------------
async def tts_all(tasks, voice):
    try:
        import edge_tts
        edge_ok = True
    except Exception:
        edge_ok = False
    for text, path in tasks:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        done = False
        if edge_ok:
            try:
                import asyncio as _a
                comm = edge_tts.Communicate(text=text, voice=voice, rate="+8%")
                async def _write():
                    with open(path, "wb") as fh:
                        async for chunk in comm.stream():
                            if chunk["type"] == "audio": fh.write(chunk["data"])
                await _a.wait_for(_write(), timeout=55)
                say(f"tts[edge] → {os.path.basename(path)} ({os.path.getsize(path)//1024}KB)")
                done = os.path.getsize(path) > 2000
            except Exception as e:
                say(f"tts[edge] fail ({str(e)[:80]}) — trying gTTS…")
        if not done:
            try:  # Google TTS public endpoint — Marathi, no key, datacenter-friendly
                from gtts import gTTS
                import asyncio as _a
                def _g():
                    gTTS(text=text[:1900], lang="mr").save(path)
                await _a.wait_for(_a.get_event_loop().run_in_executor(None, _g), timeout=55)
                say(f"tts[gTTS] → {os.path.basename(path)} ({os.path.getsize(path)//1024}KB)")
                done = os.path.getsize(path) > 2000
            except Exception as e:
                say(f"tts[gTTS] fail ({str(e)[:80]})")
        if not done:
            subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
                            "-t", "6", "-q:a", "9", "-acodec", "libmp3lame", path],
                           check=False, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
            say(f"tts[silent placeholder, 6s] → {os.path.basename(path)}")


# ------------------ ffmpeg assembly ------------------
def still_with_audio(img_path, aud_path, seg_path, zoom=True):
    dur = dur_of(aud_path) + 0.5
    say(f"  seg {os.path.basename(seg_path)} dur={dur:.1f}s")
    filt = f"[0:v]scale={W}:{H},zoompan=z='min(zoom+0.0007,1.12)':d={FPS*40}:fps={FPS}:s={W}x{H}[v]" if zoom else f"[0:v]scale={W}:{H}[v]"
    filt += f";[1:a]aresample=48000,volume=1.6[a]"
    run(["ffmpeg", "-y", "-loop", "1", "-i", img_path, "-i", aud_path,
         "-filter_complex", filt, "-map", "[v]", "-map", "[a]", "-t", f"{dur:.2f}",
         "-c:v", "libx264", "-tune", "stillimage",
         "-c:a", "aac", "-b:a", "128k", "-pix_fmt", "yuv420p", "-r", str(FPS), seg_path])

def synth_ticks(path, dur=4.6, sr=44100, freq=940):
    """Pure-Python tick track: 180ms beep once per second — zero ffmpeg-expression risk."""
    import wave, struct, math
    N = int(dur * sr); frames = bytearray()
    for i in range(N):
        t = i / sr
        env = 1.0 if (t % 1.0) > 0.82 else 0.0
        v = int(14000 * env * math.sin(2 * math.pi * freq * t))
        frames += struct.pack('<h', v)
    wv = wave.open(path, 'wb'); wv.setparams((1, 2, sr, N, 'NONE', 'not compressed'))
    wv.writeframes(bytes(frames)); wv.close()

def tick_seg(img_path, seg_path, dur=4.6):
    tick_wav = seg_path.replace('.mp4', '_ticks.wav')
    synth_ticks(tick_wav, dur)
    filt = (f"[0:v]scale={W}:{H}[v];"
            f"[1:a]aresample=48000,volume=0.9[a]")
    say(f"  seg {os.path.basename(seg_path)} dur={dur:.1f}s (ticks)")
    run(["ffmpeg", "-y", "-loop", "1", "-t", str(dur), "-i", img_path, "-i", tick_wav,
         "-filter_complex", filt, "-map", "[v]", "-map", "[a]", "-t", str(dur),
         "-c:v", "libx264", "-tune", "stillimage", "-c:a", "aac", "-b:a", "128k", "-pix_fmt", "yuv420p", "-r", str(FPS), seg_path])
    os.remove(tick_wav)

def pad_seg(img_path, aud_path, seg_path):  # voice + faint ambient bed (intro/outro)
    dur = dur_of(aud_path) + 0.6
    say(f"  seg {os.path.basename(seg_path)} dur={dur:.1f}s (pad bed)")
    filt = (f"[0:v]scale={W}:{H}[v];"
            f"[1:a]aresample=48000,volume=1.6[vo];"
            f"[2:a]aresample=48000,volume=0.10,lowpass=f=600,atrim=0:{dur:.2f}[bed];"
            f"[vo][bed]amix=inputs=2:duration=first[a]")
    run(["ffmpeg", "-y", "-loop", "1", "-t", f"{dur:.2f}", "-i", img_path, "-i", aud_path,
         "-f", "lavfi", "-i", f"anoisesrc=color=brown:duration={int(dur)+1}",
         "-filter_complex", filt, "-map", "[v]", "-map", "[a]", "-t", f"{dur:.2f}",
         "-c:v", "libx264", "-tune", "stillimage",
         "-c:a", "aac", "-b:a", "128k", "-pix_fmt", "yuv420p", "-r", str(FPS), seg_path])


# ------------------ script (Groq, optional) ------------------
def hook_cta(topic):
    hook = (f"नमस्कार! Mmindpower मध्ये स्वागत आहे. आजचा विषय — {topic}. "
            "प्रत्येक प्रश्नानंतर फक्त पाच सेकंद… लगेच उत्तर देखील. शेवटपर्यंत राहा, स्कोअर नोंद करा!")
    cta = ("चॅनेलला Subscribe करा आणि टेलिग्रामवर @mmindpower_1 मध्ये रोज नव्वद प्रश्नांचा सराव करा. "
           "फ्री प्रॅक्टिस ॲपची लिंक डिस्क्रिप्शनमध्ये आहे. उद्या नवीन टेस्ट, नवीन स्पर्धा. जय महाराष्ट्र!")
    gk = os.environ.get("GROQ_KEY")
    if not gk:
        return hook, cta
    try:
        import requests
        r = requests.post("https://api.groq.com/openai/v1/chat/completions",
                          headers={"Authorization": f"Bearer {gk}"},
                          json={"model": "openai/gpt-oss-120b", "temperature": 0.7,
                                "messages": [
                                    {"role": "system", "content": "You write short Marathi YouTube narration lines. Output strict JSON only."},
                                    {"role": "user", "content":
                                        (f'Topic: "{topic}". Return JSON {{"hook": <2-line Marathi welcome+energetic hook>, '
                                         '"cta": <2-line Marathi subscribe+telegram CTA mentioning @mmindpower_1>}. No emojis.')}]},
                          timeout=60)
        txt = r.json()["choices"][0]["message"]["content"].strip().strip("`").strip()
        if txt.startswith("{"):  # strip possible code fences
            j = json.loads(txt[txt.index("{"):txt.rindex("}")+1])
            if j.get("hook") and j.get("cta"): return j["hook"].strip(), j["cta"].strip()
    except Exception as e:
        say("groq hook failed (fallback in use): " + str(e)[:120])
    return hook, cta


# ------------------ main ------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", default="MPSC टलाठी स्पेशल")
    ap.add_argument("--set", default="")
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--voice", default="mr-IN-ManoharNeural")
    ap.add_argument("--preview", action="store_true")
    a = ap.parse_args()
    n = 1 if a.preview else a.n
    os.makedirs(OUT, exist_ok=True)
    work = os.path.join(OUT, "seg"); os.makedirs(work, exist_ok=True)

    # pick set & questions (deterministic per calendar day so series stay stable)
    files = sorted(glob.glob(os.path.join(ROOT, "quiz_data_*.json")), key=lambda p: (len(p), p))
    assert files, "no quiz data found"
    sid = a.set.upper() if a.set else os.path.basename(files[int(datetime.datetime.now().strftime("%j")) % len(files)])[10:-5]
    data = json.load(open(os.path.join(ROOT, f"quiz_data_{sid}.json"), encoding="utf-8"))
    pool = [q for q in data if "|" not in (q.get("q_marathi") or "") and q.get("options") and len(q["options"]) >= 4]
    rnd = random.Random(datetime.datetime.now().strftime("%Y%m%d") + sid)
    rnd.shuffle(pool)
    qs = pool[:n]
    assert qs, "no usable questions"

    say(f"topic={a.topic!r} set={sid} n={n} voice={a.voice}")
    hook, cta = hook_cta(a.topic)

    # 1) cards
    cards, names = [], []
    intro = intro_card(a.topic, n); p = os.path.join(work, "card_intro.png"); intro.save(p); cards.append(p); names.append("intro")
    for i, q in enumerate(qs):
        pc = os.path.join(work, f"card_q{i}.png"); question_card(i, n, q).save(pc)
        pa = os.path.join(work, f"card_a{i}.png"); answer_card(i, n, q, q.get("explanation_marathi") or "").save(pa)
        cards += [pc, pa]; names += [f"q{i}", f"a{i}"]
    ca, th = outro_card(cta)
    po = os.path.join(work, "card_outro.png"); ca.save(po)
    ca2 = os.path.join(work, "card_cta.png"); th.save(ca2)
    th.save(os.path.join(OUT, "thumbnail.png")); say("thumbnail.png minted")

    # 2) voice tracks
    tasks = [(hook, os.path.join(work, "v_intro.mp3"))]
    for i, q in enumerate(qs):
        opts = " ".join(f"{'ABCD'[j]} — {o}." for j, o in enumerate(q["options"][:4]))
        tasks.append((f"प्रश्न क्रमांक {i+1}. {q['q_marathi']} पर्यायः {opts}", os.path.join(work, f"v_q{i}.mp3")))
        ci = q.get("correct_index", 0)
        expl = (q.get("explanation_marathi") or "").strip()
        tasks.append((f"योग्य उत्तर {'ABCD'[ci]} — {q['options'][ci]}. {expl}", os.path.join(work, f"v_a{i}.mp3")))
    tasks.append((cta, os.path.join(work, "v_outro.mp3")))
    import asyncio
    asyncio.run(tts_all(tasks, a.voice))

    # 3) segments
    segs = []
    pad_seg(cards[0], os.path.join(work, "v_intro.mp3"), os.path.join(work, "seg_intro.mp4")); segs.append("seg_intro.mp4")
    for i in range(n):
        still_with_audio(cards[1 + i*2], os.path.join(work, f"v_q{i}.mp3"), os.path.join(work, f"seg_q{i}.mp4")); segs.append(f"seg_q{i}.mp4")
        tick_seg(cards[1 + i*2], os.path.join(work, f"seg_t{i}.mp4")); segs.append(f"seg_t{i}.mp4")
        still_with_audio(cards[2 + i*2], os.path.join(work, f"v_a{i}.mp3"), os.path.join(work, f"seg_a{i}.mp4")); segs.append(f"seg_a{i}.mp4")
    pad_seg(po, os.path.join(work, "v_outro.mp3"), os.path.join(work, "seg_outro.mp4")); segs.append("seg_outro.mp4")
    still_with_audio(ca2, os.path.join(work, "v_outro.mp3") if False else os.path.join(work, "v_intro.mp3"), os.path.join(work, "seg_brand.mp4"), zoom=False)
    segs.append("seg_brand.mp4")

    lst = os.path.join(work, "list.txt")
    open(lst, "w").write("\n".join(f"file '{os.path.join(work, s)}'" for s in segs))
    final = os.path.join(OUT, "final.mp4")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", final + ".tmp.mp4"])
    run(["ffmpeg", "-y", "-i", final + ".tmp.mp4", "-c", "copy", "-movflags", "+faststart", final])
    os.remove(final + ".tmp.mp4")
    meta = {"topic": a.topic, "set": sid, "questions": n, "hook": hook, "cta": cta,
            "file": final, "bytes": os.path.getsize(final),
            "date": datetime.datetime.now().isoformat(timespec="seconds")}
    json.dump(meta, open(os.path.join(OUT, "meta.json"), "w"), ensure_ascii=False, indent=2)
    say(f"DONE → {final} ({meta['bytes']//1024//1024} MB)")


if __name__ == "__main__":
    main()
