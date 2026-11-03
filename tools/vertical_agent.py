#!/usr/bin/env python3
"""vertical_agent.py — Phase B: Disney-type vertical animated documentary.

Multi-agent pipeline:
  Director(Groq) → VisualDirector×N(Groq) → ImageMaker(Pollinations)×scenes
  → Animator(ffmpeg motion) ×scenes → Voice(edge-tts) → Assembler(concat+bed)
Output: 1080x1920 vertical mp4 (~6 min), zero questions, narration-only.
"""
import argparse, asyncio, hashlib, json, os, re, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out_vertical")
W, H = 720, 1280
FPS = 25
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from groq2stage import make_chat, question_lint, marathi_lint, SYS_HI, _grab  # noqa
import video_explainer as VE   # reuse: dur_of, run, say, tts_all, doc_card helpers

say = VE.say
run = VE.run

STYLE_PREFIX = ("3D animated movie style, warm cinematic lighting, expressive characters, "
                "rich vibrant colors, soft global illumination, family-friendly animated feature film look, "
                "high detail, vertical composition. ")

PROMPT_VDIR = """Documentary chapter: "{heading}" — topic "{topic}"
Ye chapter ek SHORT vertical animated documentary ka hissa hai (Disney/Pixar-jaisa style).
Character bible (har scene mein SAME characters): {bible}

Sirf EXACT {n} scene lines do (plain text, kuch aur nahi):
S1: <visual prompt ENGLISH mein 18-30 words — same style/characters, ek clear visual moment> | <Hinglish on-screen caption ≤5 shabd ya X> | <motion: zoom_in | zoom_out | pan_left | pan_up | float>
S2: ...
(Exactly {n} S-lines; scenes story beats follow karein: establishing → detail → action → emotion → wide → close)
RULES: koi real logo/text/letter scene prompt mein NAHI; historical India 1857 era authentic; violence family-friendly (no blood)."""

PROMPT_VDOC = """Topic: "{topic}"
Reference:
{ground}

Role: tum ek viral vertical animated documentary kii script likh rahe ho. PURE Hinglish (Devanagari Hindi + English), Gen-Z energy, storytelling; ZERO questions (kisi line mein '?' nahi); repetition zero; no intro/title — cold open.
Sirf YA lines do:
TITLE: <4-7 shabd catchy Hinglish title>
CHARS: <character bible ENGLISH mein — main recurring characters/lead look 15-25 words — e.g. 'an 80 year old Indian Rajput king, long white beard, red turban, orange shawl, strong built riding white horse'>
COLD: <1-2 vaakya most dramatic visual moment se shuru>
CH1: <sub-topic heading 2-3 shabd>
...
(Exactly {nsec} CH lines; arc: world → hero → struggle → turning point → climax → cost → legacy)
OUTRO: <2 vaakya emotional close + ekta ka message>
CTA: <1 vaakya — Mmindpower Subscribe + Telegram @mmindpower_1>"""

PROMPT_VNARR = """Vertical chapter {i}/{total}: "{heading}" — "{topic}"
Reference: {ground}
{prev_block}
RULES: no questions, no repeat, punchy Gen-Z Hinglish, 95-125 shabd, har 2-3 vaakya ek visual beat ho.
Sirf ek line: NARR: <narration>"""


def pollin_img(prompt, path, seed, tries=3):
    import requests
    UA = {"User-Agent": "MmindpowerEdu/1.0 (educational vertical film)"}
    u = "https://image.pollinations.ai/prompt/" + requests.utils.quote(prompt)
    for t in range(tries):
        try:
            r = requests.get(u, params={"width": "720", "height": "1280", "nologo": "true",
                                        "model": "flux", "seed": str(seed)},
                             headers=UA, timeout=150)
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
                open(path, "wb").write(r.content)
                return path
        except Exception as e:
            say("pollinations retry %d (%s)" % (t + 1, str(e)[:50]))
        time.sleep(3 + 2 * t)
    return None


def cap_pill(text, font, d):
    """Disney-chunky rounded caption pill, bottom-center."""
    from PIL import ImageDraw
    if not text or text.upper() == "X":
        return
    try:
        bbox = d.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    except Exception:
        tw, th = d.textsize(text, font=font)
    pad_x, pad_y = 36, 22
    pw, ph = tw + pad_x * 2, th + pad_y * 2
    x0, y0 = (W - pw) // 2, H - ph - 90
    lay = d
    lay.rounded_rectangle((x0, y0, x0 + pw, y0 + ph), radius=34, fill=(12, 12, 20, 205))
    lay.rounded_rectangle((x0, y0, x0 + pw, y0 + ph), radius=34, outline=(255, 205, 78, 255), width=5)
    lay.text((W // 2, y0 + ph // 2 - 4), text, font=font, fill=(255, 244, 222), anchor="mm")


def ensure_font():
    fb = os.path.join(ROOT, "assets", "fonts", "NotoSansDevanagari-Bold.ttf")
    if not os.path.exists(fb) or os.path.getsize(fb) < 10000:
        os.makedirs(os.path.dirname(fb), exist_ok=True)
        import requests
        u = "https://github.com/notofonts/notofonts.github.io/raw/main/fonts/NotoSansDevanagari/hinted/ttf/NotoSansDevanagari-Bold.ttf"
        b = requests.get(u, timeout=60).content
        open(fb, "wb").write(b)
        say("devanagari font fetched")
    return fb


def scene_frame(img_path, caption, out):
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
    fb = ensure_font()
    im = Image.open(img_path).convert("RGB")
    r = max(W / im.width, H / im.height)
    im = im.resize((int(im.width * r), int(im.height * r)))
    x, y = (im.width - W) // 2, (im.height - H) // 2
    im = im.crop((x, y, x + W, y + H))
    # gentle warm grade + vignette
    r0, g0, b0 = im.split()
    im = Image.merge("RGB", (r0.point(lambda i: min(255, i * 1.1)),
                             g0.point(lambda i: min(255, i * 1.0)),
                             b0.point(lambda i: i * 0.88)))
    from PIL import Image as _I
    mask = _I.new("L", (W, H), 0)
    md = ImageDraw.Draw(mask)
    md.ellipse((-W * 0.3, -H * 0.3, W * 1.3, H * 1.3), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(90))
    im = _I.composite(im, _I.new("RGB", (W, H), (16, 12, 10)), mask)
    layer = im.convert("RGBA")
    d = ImageDraw.Draw(layer)
    fnt = ImageFont.truetype(fb, 44)
    cap_pill(caption, fnt, d)
    layer.convert("RGB").save(out, quality=92)
    return out


def anim_scene(frame, dur, motion, out):
    """One moving scene clip (video only)."""
    t = int(dur * FPS)
    if motion == "zoom_in":
        z = f"zoompan=z='1+0.16*on/{t}':d={t}:fps={FPS}:s={W}x{H}"
    elif motion == "zoom_out":
        z = f"zoompan=z='1.18-0.16*on/{t}':d={t}:fps={FPS}:s={W}x{H}"
    elif motion == "pan_left":
        big = 1400
        z = (f"scale={big}:-2,crop=w={W}:h={H}:x='({big}-{W})*t/{dur}':y='(ih-{H})/2'")
    elif motion == "pan_up":
        big = 2200
        z = (f"scale=-2:{big},crop=w={W}:h={H}:y='(in_h-{H})*(1-t/{dur})':x='(iw-{W})/2'")
    else:  # float — gentle breathing zoom + micro rotate
        z = (f"zoompan=z='1.06+0.03*sin(on/{FPS})':d={t}:fps={FPS}:s={W}x{H},"
             f"rotate=a=0.008*sin(2*PI*t/3):fillcolor=black")
    vf = z + ",fade=t=in:st=0:d=0.3,fade=t=out:st=%.2f:d=0.3" % (dur - 0.3)
    run(["ffmpeg", "-y", "-loop", "1", "-t", f"{dur:.2f}", "-i", frame,
         "-filter:v", vf, "-an", "-t", f"{dur:.2f}", "-c:v", "libx264",
         "-b:v", "2600k", "-maxrate", "3000k", "-bufsize", "6000k",
         "-pix_fmt", "yuv420p", "-r", str(FPS), out])
    return out


def vdoc_fallback(seed, topic, nsec=6):
    sub = ((seed or {}).get("subtopic") or topic).strip()
    arcs = ["Aandhi se pehle", "Nayak", "Pehla clash", "Pressure", "Comeback", "Legacy"]
    heads = (arcs + arcs)[:nsec]
    ex = ((seed or {}).get("explanation") or "").replace("?", "।")
    sents = [x.strip() for x in ex.split("।") if len(x.strip()) > 6]
    chs = []
    for i, h in enumerate(heads):
        core = "। ".join(sents[i % max(len(sents), 1):(i % max(len(sents), 1)) + 2])
        chs.append({"heading": h, "narration": (core + "। " + "Ye chapter " + h + " par focus karta hai.").strip(),
                    "scenes": []})
    return {"title": "Vertical Doc: " + sub, "chars": "main historical figure of " + sub + ", consistent look",
            "cold": "Kahani shuru hoti hai ek aise pal se jahan itihaas mod gaya.",
            "chapters": chs,
            "outro": "Ye thi us daur ki kahani — jisme sab kuch daav par laga tha.",
            "cta": "Mmindpower Subscribe karo — Telegram @mmindpower_1 pe roz episodes.",
            "style": "vertical", "_fallback": True}


def director_script(topic, ground, nsec, seed):
    gk = os.environ.get("GROQ_KEY")
    chat = make_chat(gk) if gk else None
    if not chat:
        return None
    see = ""
    if seed:
        see = ("\nCORE FACTS: " + seed.get("question", "") + " | Sahi: " + seed.get("answer", "")
               + " | " + seed.get("explanation", ""))[:600]
    A = chat(PROMPT_VDOC.format(topic=topic, ground=(ground + see)[:1500], nsec=nsec), mx=2000, sysmsg=SYS_HI)
    if not A:
        return None
    title = _grab(r"^TITLE:\s*(.+)$", A) or topic
    chars = _grab(r"^CHARS:\s*(.+)$", A) or "main historical figure, consistent look"
    cold = _grab(r"^COLD:\s*(.+)$", A) or ""
    outro = _grab(r"^OUTRO:\s*(.+)$", A) or ""
    cta = _grab(r"^CTA:\s*(.+)$", A) or ""
    heads = [m.group(1).strip()[:40] for m in re.finditer(r"^CH\d+\s*[:\-]\s*(.+)$", A, re.M)]
    if len(heads) < 4:
        return None
    heads = heads[:nsec]
    prevs = []
    chapters = []
    for i, h in enumerate(heads):
        pb = ("\nALREADY COVERED (repeat mat karo):\n" + " ".join(prevs)[:600]) if prevs else ""
        B = chat(PROMPT_VNARR.format(topic=topic, i=i + 1, total=len(heads), heading=h,
                                     ground=ground[:1000], prev_block=pb), mx=700, sysmsg=SYS_HI)
        narr = ""
        if B:
            mm = re.search(r"NARR\s*:\s*(.+)$", B, re.S)
            narr = re.sub(r"\s+", " ", mm.group(1)).strip() if mm else ""
        if not narr:
            return None
        prevs.append(narr)
        chapters.append({"heading": h, "narration": narr[:1100], "scenes": []})
    return {"title": title, "chars": chars, "cold": cold, "chapters": chapters,
            "outro": outro, "cta": cta, "style": "vertical"}


def visual_director(topic, ch, bible, nsc=6):
    gk = os.environ.get("GROQ_KEY")
    chat = make_chat(gk) if gk else None
    scenes = []
    if chat:
        s = chat(PROMPT_VDIR.format(heading=ch["heading"], topic=topic, bible=bible, n=nsc),
                 mx=1300, sysmsg=SYS_HI)
        for m in re.finditer(r"^S\d+\s*[:\-]\s*(.+)$", s or "", re.M):
            parts = [p.strip() for p in re.split(r"[|｜]", m.group(1))]
            while len(parts) < 3:
                parts.append("")
            mo = parts[2].lower()
            if mo not in ("zoom_in", "zoom_out", "pan_left", "pan_up", "float"):
                mo = "float"
            scenes.append({"prompt": parts[0][:260], "cap": parts[1][:24], "motion": mo})
    if len(scenes) < 3:
        base = ch["heading"]
        defaults = [("wide establishing shot of " + base, "", "pan_left"),
                    ("mid shot emotional moment — " + base, "", "zoom_in"),
                    ("detail close-up dramatic light — " + base, "", "float"),
                    ("action sequence dramatic — " + base, "", "pan_up"),
                    ("wide finale golden light — " + base, "", "zoom_out")]
        scenes = [{"prompt": p, "cap": "", "motion": m} for p, _, m in defaults]
    return scenes[:nsc]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", required=True)
    ap.add_argument("--seed-file", default="")
    ap.add_argument("--chapters", type=int, default=7)
    ap.add_argument("--scenes-per-chapter", type=int, default=6)
    ap.add_argument("--voice", default="hi-IN-SwaraNeural")
    a = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)
    work = os.path.join(OUT, "w"); os.makedirs(work, exist_ok=True)

    seed = None
    if a.seed_file and os.path.exists(a.seed_file):
        seed = json.load(open(a.seed_file, encoding="utf-8"))
        say("vertical seed: " + seed["question"][:60])

    cache = os.path.join(OUT, "vscript.json")
    if os.path.exists(cache):
        vd = json.load(open(cache)); say("vscript cache hit")
    else:
        ground = VE.wiki_ground(a.topic) or ""
        vd = director_script(a.topic, ground, a.chapters, seed)
        if not vd:
            say("director offline → fallback script")
            vd = vdoc_fallback(seed, a.topic, min(a.chapters, 6))
        vd = question_lint(vd); vd = marathi_lint(vd)
        if vd.get("_questions_dropped"):
            say("zero-question QC dropped %d" % vd["_questions_dropped"])
        json.dump(vd, open(cache, "w"), ensure_ascii=False, indent=2)

    bible = vd.get("chars") or "consistent main character"
    fseed = int(hashlib.md5((a.topic).encode()).hexdigest()[:6], 16)

    # ---- per-chapter agent squads ----
    all_media = []  # list of (scene_frames[], motion[], narration_text, heading)
    for ci, ch in enumerate(vd["chapters"]):
        scenes = ch.get("scenes") or visual_director(a.topic, ch, bible, a.scenes_per_chapter)
        ch["scenes"] = scenes     # cache for reruns
        frames, motions = [], []
        for si, sc in enumerate(scenes):
            p = STYLE_PREFIX + " Character bible: " + bible + ". Scene: " + sc["prompt"]
            raw = os.path.join(work, f"v{ci:02d}_{si:02d}.jpg")
            got = pollin_img(p, raw, fseed + ci * 10 + si)
            if not got:
                got = VE.doc_card(sc["cap"] or ch["heading"], ch["heading"], raw)
            fr = scene_frame(raw, sc.get("cap", ""), os.path.join(work, f"vs{ci:02d}_{si:02d}.png"))
            frames.append(fr); motions.append(sc.get("motion", "float"))
            say(f"scene c{ci+1}/s{si+1} ready ({sc.get('motion')})")
        all_media.append((frames, motions, ch["narration"], ch["heading"]))
        json.dump(vd, open(cache, "w"), ensure_ascii=False, indent=2)   # checkpoint scenes

    # ---- voice agent ----
    tasks, plan = [], []
    ca = os.path.join(work, "vcold.mp3")
    tasks.append((vd.get("cold", vd["title"]), ca))
    plan.append(("cold", ca))
    for ci, (_, _, narr, _) in enumerate(all_media):
        au = os.path.join(work, f"vn{ci}.mp3")
        tasks.append((narr[:1400], au)); plan.append((f"ch{ci}", au))
    oa = os.path.join(work, "vout.mp3")
    tasks.append(((vd.get("outro", "") + " Music: Sascha Ende, Epic Drone Shots (CC-BY 4.0) via Wikimedia Commons. " + vd.get("cta", "")).strip(), oa))
    plan.append(("outro", oa))
    asyncio.run(VE.tts_all(tasks, a.voice, "+0Hz", "+6%"))

    # ---- animator + assembler ----
    segs = []

    def bedded(mp3):
        mx = mp3.replace(".mp3", "_mx.mp3")
        VE.mix_bed_on(mp3, mx)
        return mx

    # cold open scene: first chapter first frame, breathing zoom
    coldmx = bedded(ca)
    d0 = VE.dur_of(coldmx) + 0.4
    fr0 = all_media[0][0][0]
    anim_scene(fr0, d0, "zoom_in", os.path.join(work, "seg_cold.mp4"))
    # mux audio
    run(["ffmpeg", "-y", "-i", os.path.join(work, "seg_cold.mp4"), "-i", coldmx, "-map", "0:v",
         "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "96k", "-shortest",
         os.path.join(work, "fcold.mp4")])
    segs.append(os.path.join(work, "fcold.mp4"))

    for ci, (frames, motions, narr, heading) in enumerate(all_media):
        mx = bedded(os.path.join(work, f"vn{ci}.mp3"))
        cdur = VE.dur_of(mx) + 0.4
        per = cdur / len(frames)
        chsegs = []
        for si, fp in enumerate(frames):
            sp = os.path.join(work, f"seg_{ci}_{si}.mp4")
            anim_scene(fp, per, motions[si], sp)
            chsegs.append(sp)
        lst = os.path.join(work, f"chlist{ci}.txt")
        open(lst, "w").write("\n".join(f"file '{x}'" for x in chsegs))
        chv = os.path.join(work, f"chv{ci}.mp4")
        run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", chv])
        run(["ffmpeg", "-y", "-i", chv, "-i", mx, "-map", "0:v", "-map", "1:a",
             "-c:v", "copy", "-c:a", "aac", "-b:a", "96k", "-shortest",
             os.path.join(work, f"fch{ci}.mp4")])
        segs.append(os.path.join(work, f"fch{ci}.mp4"))
        say(f"chapter {ci+1} assembled ({cdur:.0f}s)")

    outs = bedded(oa)
    dout = VE.dur_of(outs) + 0.4
    lfr = all_media[-1][0][-1]
    anim_scene(lfr, dout, "zoom_out", os.path.join(work, "seg_out.mp4"))
    run(["ffmpeg", "-y", "-i", os.path.join(work, "seg_out.mp4"), "-i", outs, "-map", "0:v",
         "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "96k", "-shortest",
         os.path.join(work, "fout.mp4")])
    segs.append(os.path.join(work, "fout.mp4"))

    lst = os.path.join(work, "vlist.txt")
    open(lst, "w").write("\n".join(f"file '{x}'" for x in segs))
    final = os.path.join(OUT, "vertical.mp4")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", final + ".tmp.mp4"])
    run(["ffmpeg", "-y", "-i", final + ".tmp.mp4", "-c", "copy", "-movflags", "+faststart", final])
    os.remove(final + ".tmp.mp4")
    if os.path.getsize(final) > 46 * 1024 * 1024:
        say("vertical >46MB → re-encode 2.2M")
        run(["ffmpeg", "-y", "-i", final, "-c:v", "libx264", "-b:v", "2200k", "-maxrate", "2500k",
             "-bufsize", "5000k", "-c:a", "aac", "-b:a", "80k", "-movflags", "+faststart", final + ".sm.mp4"])
        os.replace(final + ".sm.mp4", final)
    tot = sum(VE.dur_of(x) for x in segs if x.endswith(".mp4"))
    meta = {"topic": vd["title"], "style": "vertical-animated", "chapters": [c["heading"] for c in vd["chapters"]],
            "minutes": round(tot / 60, 1), "bytes": os.path.getsize(final),
            "scenes_per_chapter": a.scenes_per_chapter, "music": "Sascha Ende — Epic Drone Shots (CC-BY 4.0)",
            "date": time.strftime("%Y-%m-%d %H:%M:%S")}
    json.dump(meta, open(os.path.join(OUT, "vmeta.json"), "w"), ensure_ascii=False, indent=2)
    say(f"VERTICAL DONE → {final} ({meta['bytes']//1024//1024}MB · {meta['minutes']} min)")


if __name__ == "__main__":
    main()
