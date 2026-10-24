# tools/groq2stage.py — shared by video_explainer; 2-stage line-protocol scripting (no strict-JSON gamble)
import os
import re
import time


def say(m):
    print(time.strftime("[%H:%M:%S]"), m, flush=True)


SYS = ("You are a Marathi educational scriptwriter for MPSC-style explainer videos. "
       "Follow the requested FORMAT exactly. Plain text only — no JSON, no markdown fences.")
MODELS = ("openai/gpt-oss-120b",
          "meta-llama/llama-4-scout-17b-16e-instruct",
          "qwen/qwen3-32b",
          "llama-3.1-8b-instant")
KINDS = ("concept", "compare", "steps", "def")


def make_chat(gk):
    import requests

    def chat(user, temp=0.45, mx=1400):
        for mdl in MODELS:
            try:
                r = requests.post("https://api.groq.com/openai/v1/chat/completions",
                                  headers={"Authorization": "Bearer " + gk},
                                  json={"model": mdl, "temperature": temp, "max_tokens": mx,
                                        "messages": [{"role": "system", "content": SYS},
                                                     {"role": "user", "content": user}]},
                                  timeout=120)
                txt = r.json()["choices"][0]["message"]["content"].strip()
                say("groq ok via {} ({} ch)".format(mdl, len(txt)))
                return txt
            except Exception as e:
                say("groq [{}] fail: {}".format(mdl, str(e)[:80]))
        return None
    return chat


def _grab(pat, txt, default=""):
    m = re.search(pat, txt, re.M)
    return m.group(1).strip() if m else default


PROMPT_A_TPL = """विषय: "{topic}"
संदर्भ (विकिपीडिया):
{ground}

खालील प्रकारे उत्तर लिहा — फक्त या ओळी, इतर काहीही नाही:
HOOK: <२ वाक्ये, मराठी, उत्सुकता निर्माण करणारी>
CH1: <शीर्षक — महत्त्वाचा मुद्दा १> | <concept/compare/steps/def पैकी एक> | <चिप१, चिप२>
CH2: ...
(अशा एकूण {nsec} CH ओळी — प्रत्येकी विशिष्ट उपविषय असावा)
RECAP: <२-३ वाक्यांचा सारांश, मराठी>
CTA: <१ वाक्य — Mmindpower ला Subscribe आणि टेलिग्राम @mmindpower_1 वर रोज सरावासाठी आवाहन>"""

PROMPT_B_TPL = """विषय: "{topic}" — स्पष्टीकरण व्हिडिओ (प्रकरण {i} / {total})
प्रकरण शीर्षक: "{heading}" — प्रकार: {kind}
संदर्भ:
{ground}

फक्त खालील स्वरूपात उत्तर (इतर काहीही नाही):
NARR: <मराठीत ५५-८५ शब्द, बोलभाषा, सोपी उदाहरणे; तथ्य/आकडेवारी असेल तर समाविष्ट करा>
- <बुलेट १ : १२ शब्दांपेक्षा कमी>
- <बुलेट २>
- <बुलेट ३>"""


def groq_script_2stage(topic, ground, nsec, outdir):
    """Returns script dict on success, None on any failure (caller falls back)."""
    gk = os.environ.get("GROQ_KEY")
    if not gk:
        return None
    chat = make_chat(gk)

    A = chat(PROMPT_A_TPL.format(topic=topic, ground=ground[:1600], nsec=nsec), mx=1200)
    if not A:
        say("stageA empty")
        return None
    hook = _grab(r"^HOOK:\s*(.+)$", A)
    recap = _grab(r"^RECAP:\s*(.+)$", A)
    cta = _grab(r"^CTA:\s*(.+)$", A)
    outs = []
    for m in re.finditer(r"^CH\d+\s*[:\-]\s*(.+)$", A, re.M):
        parts = [p.strip() for p in re.split(r"[|｜]", m.group(1))]
        while len(parts) < 3:
            parts.append("")
        heading, kind, chips = parts[0], parts[1].lower(), parts[2]
        kind = kind if kind in KINDS else "concept"
        outs.append({"heading": heading[:60], "kind": kind,
                     "chips": [c.strip()[:18] for c in re.split(r"[,，;]", chips) if c.strip()][:4]})
    if len(outs) < max(3, nsec - 1):
        say("outline parse got {}".format(len(outs)))
        try:
            os.makedirs(outdir, exist_ok=True)
            open(os.path.join(outdir, "groq_debug.txt"), "w").write("STAGE A RAW:\n" + A)
        except Exception:
            pass
        return None
    outs = outs[:nsec]

    done = []
    for i, ch in enumerate(outs):
        B = chat(PROMPT_B_TPL.format(topic=topic, i=i + 1, total=len(outs),
                                     heading=ch["heading"], kind=ch["kind"],
                                     ground=ground[:1200]), mx=900)
        if not B:
            say("stageB empty chap{}".format(i + 1))
            return None
        mm = re.search(r"NARR\s*:\s*(.+?)(?=\n\s*[-–•]|\Z)", B, re.S)
        narr = re.sub(r"\s+", " ", mm.group(1)).strip() if mm else ""
        bullets = [ln.strip().lstrip("-–• ").strip() for ln in B.splitlines()
                   if ln.strip()[:1] in ("-", "–", "•")][:4]
        if not narr:
            say("no NARR chap{}".format(i + 1))
            return None
        done.append(dict(ch, narration=narr, bullets=bullets or [ch["heading"]]))

    sc = {"title": topic,
          "hook": hook or ("नमस्कार! आज आपण " + topic + " हा विषय सविस्तर समजून घेणार आहोत."),
          "chapters": done,
          "recap": recap or (topic + " — मुख्य मुद्दे पुन्हा पाहा आणि नोट्स करा."),
          "cta": cta or "Subscribe करा आणि टेलिग्रामवर @mmindpower_1 मध्ये रोज सराव करा."}
    say("groq 2-stage script OK — {} chapters".format(len(done)))
    return sc
