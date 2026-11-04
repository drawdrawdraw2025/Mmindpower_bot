#!/usr/bin/env python3
"""Mmindpower AI-host film pipeline.

User gives a HINDI narration script (verbatim, never modified) ->
edge-tts voice (hi-IN-SwaraNeural) -> Rhubarb visemes -> Disney Pollinations story scenes
-> lip-synced AI host circle (bottom-right, drift-left/return) -> vertical 720x1280 mp4.

Usage:  python3 tools/host_film.py --script host_input/script.txt --out out_host [--scenes 10]
All services free. Needs: ffmpeg, pip(edge-tts pillow mutagen imageio-ffmpeg requests), GROQ_API_KEY (optional).
"""
import argparse, json, math, os, random, re, subprocess, sys, time, urllib.parse, wave
import requests
from PIL import Image, ImageFilter, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOST = os.path.join(ROOT, "assets", "host")
FPS, W, H = 25, 720, 1280
RH_URL = ("https://github.com/DanielSWolf/rhubarb-lip-sync/releases/download/v1.13.0/"
          "Rhubarb-Lip-Sync-1.13.0-Linux.zip")
GROQ_MODELS = ["openai/gpt-oss-120b", "llama-3.3-70b-versatile",
               "meta-llama/llama-4-maverick-17b-128e-instruct", "qwen/qwen3-32b", "llama-3.1-8b-instant"]
FALLBACK_SCENES = [
    "dense dark Indian jungle and tall hills, monsoon clouds, moody epic atmosphere, no people",
    "massive medieval Indian army marching through mountain path, war elephants, dust, stormy sky",
    "intimidating medieval general portrait, huge mustache, cruel smirk, ornate armor, low angle",
    "brave young Maratha king standing on fort ramparts at dusk, saffron turban, wind, heroic light",
    "king planning war strategy with commanders around a map inside torchlit fort chamber",
    "tense historic meeting of two leaders under royal canopy tent, hidden dagger, dramatic",
    "sudden swift counterattack closeup, steel claw weapon with sparks, dynamic action",
    "guerrilla ambush from dense forest onto confused army, mist, fast motion, epic battle",
    "battlefield chaos in mountain jungle, scattered fleeing army, smoke and dust, wide shot",
    "saffron flag on fort at golden sunrise, triumphant victory, rays of light over mountains",
]
def say(*a): print(f"[{time.strftime('%H:%M:%S')}]", *a, flush=True)
def run(c): subprocess.run(c, check=True)

def tts(script_path, work):
    mp3, vtt = os.path.join(work, "full.mp3"), os.path.join(work, "full.vtt")
    run(["python3", "-m", "edge_tts", "--voice", "hi-IN-SwaraNeural", "--file", script_path,
         "--write-media", mp3, "--write-subtitles", vtt])
    wav = os.path.join(work, "full.wav")
    run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", mp3, "-ar", "16000", "-ac", "1", wav])
    return mp3, vtt, wav

def rhubarb(wav, work):
    exe = os.path.join(work, "rhubarb", "rhubarb")
    if not os.path.exists(exe):
        z = os.path.join(work, "rh.zip")
        if not run_quiet(["curl", "-sfL", RH_URL, "-o", z]):
            raise RuntimeError("rhubarb download failed")
        run(["unzip", "-q", "-o", z, "-d", work])
        base = os.path.join(work, "Rhubarb-Lip-Sync-1.13.0-Linux")
        os.makedirs(os.path.join(work, "rhubarb"), exist_ok=True)
        for f in os.listdir(base):
            os.rename(os.path.join(base, f), os.path.join(work, "rhubarb", f))
        run(["chmod", "+x", exe])
    lips = os.path.join(work, "lips.json")
    run([exe, "-f", "json", "-o", lips, wav])
    return lips

def run_quiet(c): return subprocess.run(c).returncode == 0

def vtt_times(vtt, nsc):
    """Evenly split narration into nsc scenes by word count, using cue times."""
    cues = re.findall(r"(\d+:\d+:\d+[.,]\d+) --> [^\n]+\n([^\n]+)", open(vtt, encoding="utf8").read())
    def ts(s):
        s = s.replace(",", "."); p = s.split(":"); return int(p[0]) * 3600 + int(p[1]) * 60 + float(p[2])
    total = sum(len(t.split()) for _, t in cues); bounds = [0.0]; acc = 0.0; want = total / nsc
    for tt, txt in cues:
        acc += len(txt.split())
        if acc >= want * len(bounds) and len(bounds) < nsc:
            bounds.append(round(ts(tt), 2))
    while len(bounds) < nsc: bounds.append(bounds[-1] + 1)
    return bounds

def groq_scenes(script_text, nsc):
    key = os.environ.get("GROQ_API_KEY")
    if not key: return None
    body = {"messages": [{"role": "system", "content":
            "You are the Visual Director of a Disney-Pixar-style vertical history documentary. "
            "Read the Hindi narration and output ONLY a JSON array of exactly N english image prompts, "
            "one per chronological story beat, each prompt cinematic, vertical composition, "
            "Disney Pixar 3D animation style, Indian historical setting, no text, no watermark words."},
            {"role": "user", "content": f"N={nsc}\nNarration:\n{script_text[:6000]}"}],
            "temperature": 0.7, "max_tokens": 1500}
    for m in GROQ_MODELS:
        body["model"] = m
        try:
            r = requests.post("https://api.groq.com/openai/v1/chat/completions",
                              headers={"Authorization": f"Bearer {key}"}, json=body, timeout=90)
            if r.status_code != 200: continue
            arr = json.loads(re.search(r"\[.*\]", r.json()["choices"][0]["message"]["content"], re.S).group(0))
            if len(arr) >= nsc: return arr[:nsc]
        except Exception:
            continue
    return None

def pollinations(prompt, path, seed):
    url = (f"https://image.pollinations.ai/prompt/{urllib.parse.quote(prompt)}"
           f"?width={W}&height={H}&nologo=true&model=flux&seed={seed}")
    for att in range(4):
        try:
            r = requests.get(url, timeout=300, headers={"User-Agent": "Mmindpower/1.0"})
            if r.status_code == 200 and r.content[:1] == b"\xff" and len(r.content) > 40000:
                open(path, "wb").write(r.content); return True
            say(f"scene img retry {att + 1}: {r.status_code} {len(r.content)}")
        except Exception as e:
            say("img err", e)
        time.sleep(50)
    return False

HORDE = "https://stablehorde.net/api/v2"

def horde_image(prompt, path, timeout_s=900):
    """Engine 2: AI Horde volunteer-GPU network. Anonymous key works (slower queue);
    set HORDE_KEY secret for a registered (faster) key."""
    hdr = {"apikey": os.environ.get("HORDE_KEY", "0000000000") or "0000000000",
           "Client-Agent": "MmindpowerEdu:1.0:github"}
    body = {"prompt": prompt,
            "params": {"width": 640, "height": 1152, "steps": 25, "n": 1,
                       "sampler_name": "k_euler", "cfg_scale": 7.5},
            "nsfw": False, "r2": True,
            "models": ["AlbedoBase XL (SDXL)", "Dreamshaper", "stable_diffusion"]}
    try:
        r = requests.post(f"{HORDE}/generate/async", json=body, headers=hdr, timeout=90)
        if r.status_code != 202:
            say("horde submit failed", r.status_code); return False
        gid = r.json()["id"]; t0 = time.time()
        while time.time() - t0 < timeout_s:
            time.sleep(20)
            c = requests.get(f"{HORDE}/generate/check/{gid}", headers=hdr, timeout=60).json()
            say(f"horde wait={c.get('wait_time')} queue={c.get('queue_position')}")
            if c.get("done"):
                s = requests.get(f"{HORDE}/generate/status/{gid}", headers=hdr, timeout=60).json()
                gens = s.get("generations") or []
                if not gens: return False
                img = requests.get(gens[0]["img"], timeout=180)
                if img.status_code == 200 and len(img.content) > 20000:
                    open(path, "wb").write(img.content)
                    say("horde delivered via model:", gens[0].get("model"))
                    return True
                return False
        say("horde timeout"); return False
    except Exception as e:
        say("horde err", e); return False

def gen_image(prompt, path, seed):
    """Primary engine Pollinations(flux) → failover AI Horde (community GPUs)."""
    if pollinations(prompt, path, seed):
        say("engine=POL pollinations"); return True
    say("pollinations failed → AI Horde failover")
    if horde_image(prompt, path):
        say("engine=HOR community"); return True
    return False

def render_host(base_p, lips_p, wav_p, outdir):
    os.makedirs(outdir, exist_ok=True)
    cues = json.load(open(lips_p))["mouthCues"]; openset = {"B", "C", "D", "E", "F", "H"}
    base = Image.open(base_p).convert("RGB"); sc = 1.10
    big = base.resize((int(576 * sc), int(1024 * sc)), Image.LANCZOS)
    lay = Image.open(os.path.join(HOST, "mouth_layer.png")).convert("RGBA").resize(big.size, Image.LANCZOS)
    skin = base.crop((285, 400, 295, 410)).resize((1, 1)).getpixel((0, 0))
    with wave.open(wav_p, "rb") as wf: dur = wf.getnframes() / wf.getframerate()
    n = int(dur * FPS); nb = 2.0; ci = 0
    for i in range(n):
        t = i / FPS
        cx = 288 * sc + 14 * math.sin(2 * math.pi * t / 8.5); cy = 300 * sc + 9 * math.sin(2 * math.pi * t / 6.7)
        x0, y0 = int(cx - 240), int(cy - 240)
        fr = big.crop((x0, y0, x0 + 480, y0 + 480)).resize((250, 250), Image.LANCZOS)
        while ci < len(cues) - 1 and cues[ci]["end"] <= t: ci += 1
        if cues[ci]["start"] <= t and cues[ci]["value"] in openset:
            frl = lay.crop((x0, y0, x0 + 480, y0 + 480)).resize((250, 250), Image.LANCZOS)
            fr.paste(frl.convert("RGB"), (0, 0), frl.split()[3])
        if t >= nb:
            if t < nb + 0.18:
                pr = 1 - abs((t - nb - 0.09) / 0.09)
                l2 = Image.new("RGBA", (250, 250), (0, 0, 0, 0)); d = ImageDraw.Draw(l2)
                for exc in (262, 333):
                    bx = (exc * sc - x0) * 250 / 480; by = (330 * sc - y0) * 250 / 480
                    d.ellipse((bx - 14, by - 8, bx + 14, by - 8 + 17 * pr), fill=skin + (240,))
                fr = Image.alpha_composite(fr.convert("RGBA"), l2.filter(ImageFilter.GaussianBlur(2.5))).convert("RGB")
            else: nb = t + 3.6 + (i % 9) * 0.31
        if i % FPS == 0: say(f"host frames {i // FPS:.0f}s")
        fr.save(os.path.join(outdir, f"p{i:05d}.jpg"), quality=88)
    return n

def bg_segments(pics, bounds, work):
    durs =[round(bounds[i + 1] - bounds[i], 2) for i in range(len(pics))]
    segs = []
    for i, dur in enumerate(durs):
        sgn, gs2 = ("-", "+") if i % 2 else ("+", "-")
        mot = (f"x=(in_w-{W})/2{sgn}14*sin(2*PI*t/{9 + i % 4}):"
               f"y=(in_h-{H})/2{gs2}8*sin(2*PI*t/{11 + i % 5})")
        out = os.path.join(work, f"seg{i}.mp4")
        run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-loop", "1", "-t", str(dur), "-i", pics[i],
             "-filter_complex", f"[0:v]scale=800:1422,crop={W}:{H}:{mot},setsar=1,eq=saturation=1.05[v]",
             "-map", "[v]", "-r", str(FPS), "-c:v", "libx264", "-crf", "21", "-preset", "veryfast", out])
        segs.append(out); say("scene", i + 1, dur, "s ok")
    lst = os.path.join(work, "cat.txt"); open(lst, "w").write("\n".join(f"file '{s}'" for s in segs))
    bg = os.path.join(work, "bg.mp4")
    run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", bg])
    return bg

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--script", required=True); ap.add_argument("--out", default="out_host")
    ap.add_argument("--scenes", type=int, default=10)
    a = ap.parse_args()
    text = open(a.script, encoding="utf8").read().strip()
    work = os.path.join(a.out, "work"); os.makedirs(work, exist_ok=True)
    say("TTS…"); mp3, vtt, wav = tts(a.script, work)
    say("rhubarb visemes…"); lips = rhubarb(wav, work)
    bounds = vtt_times(vtt, a.scenes)
    with wave.open(wav, "rb") as wf: dur = wf.getnframes() / wf.getframerate()
    bounds.append(round(dur, 2)); say("scene bounds:", bounds)
    scenes = groq_scenes(text, a.scenes) or FALLBACK_SCENES * (a.scenes // 10 + 1)
    scenes = scenes[:a.scenes]
    pics = []
    for i, pr in enumerate(scenes):
        p = os.path.join(work, f"story{i}.png")
        style = (pr if "Disney" in pr else pr + ", Disney Pixar 3D animation style, cinematic vertical")
        if gen_image(style, p, 950 + i): pics.append(p)
        else:
            say("scene fallback: reuse previous")
            pics.append(pics[-1] if pics else os.path.join(HOST, "face_closed.png"))
        time.sleep(46)
    say("host frames…"); render_host(os.path.join(HOST, "face_closed.png"), lips, wav, os.path.join(work, "pf"))
    bg = bg_segments(pics, bounds, work)
    final = os.path.join(a.out, "host_film.mp4")
    say("final composite…")
    run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", bg,
         "-framerate", str(FPS), "-i", os.path.join(work, "pf", "p%05d.jpg"),
         "-i", os.path.join(HOST, "mask.png"), "-i", os.path.join(HOST, "ring.png"), "-i", mp3,
         "-filter_complex",
         "[1:v]format=rgba[h];[h][2:v]alphamerge[c];"
         "[0:v][c]overlay=x=W-262+20*sin(2*PI*t/6.5):y=H-272[tp];"
         "[tp][3:v]overlay=x=W-262+20*sin(2*PI*t/6.5):y=H-272,format=yuv420p[v]",
         "-map", "[v]", "-map", "4:a", "-c:v", "libx264", "-crf", "20", "-preset", "medium",
         "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", final])
    if os.path.getsize(final) > 46 * 1024 * 1024:
        vk = max(450, int((44 * 1024 * 1024 * 8) / dur / 1000) - 96)
        say(f">46MB → two-pass @ {vk}k")
        run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", final, "-c:v", "libx264", "-preset", "slow",
             "-b:v", f"{vk}k", "-maxrate", f"{int(vk * 1.35)}k", "-bufsize", f"{vk * 2}k",
             "-pass", "1", "-an", "-f", "null", "/dev/null"])
        run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", final, "-c:v", "libx264", "-preset", "slow",
             "-b:v", f"{vk}k", "-maxrate", f"{int(vk * 1.35)}k", "-bufsize", f"{vk * 2}k",
             "-pass", "2", "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", final + ".sm.mp4"])
        os.replace(final + ".sm.mp4", final)
    say(f"HOST FILM DONE → {final} ({os.path.getsize(final) // 1024 // 1024}MB · {dur / 60:.1f} min)")

if __name__ == "__main__":
    main()
