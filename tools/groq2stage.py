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

SYS_HI = ("You are a Gen-Z Hinglish educational scriptwriter (Hindi written in Devanagari + English terms kept as-is, "
          "e.g. 'chaliye samajhte hain', 'basically', 'exam point of view'). Follow FORMAT exactly. Plain text only — no JSON, no markdown fences.")

PROMPT_A_HI = """Topic: "{topic}"
Reference (Wikipedia):
{ground}

Sirf IN lines mein jawaab do — aur kuch nahi (lines Devanagari Hindi + English mix mein hon — bol-chaal wali, Gen-Z tone):
TITLE: <catchy Hinglish film title — 4-8 shabd; sirf Hinglish (Devanagari Hindi + English); Marathi GRAMMAR words bilkul nahi (proper nouns chalenge)>
HOOK: <2 vaakya — curiosity create kare>
CH1: <chapter title — मुद्दा १> | <concept/compare/steps/def गे ईक> | <chip1, chip2>
CH2: ...
(अशा एकूण {nsec} CH ओळी — प्रत्येकी वेगळा उपविषय)
RECAP: <2-3 vaakya summary>
CTA: <1 vaakya — Mmindpower Subscribe + Telegram @mmindpower_1 roz practice>"""

PROMPT_B_HI = """Topic: "{topic}" — explainer video (chapter {i} / {total})
Chapter title: "{heading}" — type: {kind}
Reference:
{ground}

Sirf YA format mein (kuch aur nahi):
NARR: <Hinglish — Hindi Devanagari mein + English words naturally mixed; 55-85 shabd; Gen-Z style; koi Marathi-shabd NAHI; facts accurate>
- <bullet 1 — 12 shabdon se kam>
- <bullet 2>
- <bullet 3>"""



def make_chat(gk):
    import requests

    def chat(user, temp=0.45, mx=2000, retries=2, sysmsg=SYS):
        for attempt in range(retries):
            for mdl in MODELS:
                try:
                    payload = {"model": mdl, "temperature": temp, "max_tokens": mx,
                               "messages": [{"role": "system", "content": sysmsg},
                                            {"role": "user", "content": user}]}
                    if "gpt-oss" in mdl:
                        payload["reasoning_effort"] = "low"     # stop reasoning eating the token budget
                        payload["max_completion_tokens"] = mx
                    r = requests.post("https://api.groq.com/openai/v1/chat/completions",
                                      headers={"Authorization": "Bearer " + gk},
                                      json=payload, timeout=120)
                    js = r.json()
                    txt = js["choices"][0]["message"]["content"].strip()
                    if not txt:
                        say("groq [{}] empty content (try {})".format(mdl, attempt))
                        continue
                    say("groq ok via {} ({} ch)".format(mdl, len(txt)))
                    return txt
                except Exception as e:
                    try:
                        say("groq [{}] fail: {}".format(mdl, str(r.json())[:120]))
                    except Exception:
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


DIA_A = "\n\nभाषा-शैली (महत्त्वाचे!): HOOK व CTA लहाजा कोल्हापुरी ग्रामीण बोलभाषेत लिहा — दामा ठेवा; उदा. 'आहे' ऐवजी 'असतं', 'करायला' ऐवजी 'करं', 'मग', 'का', 'बरं', 'गं' असे शब्द वापरा. मुद्दे मात्र अचूक ठेवा."
DIA_B = "\n\nभाषा-शैली (महत्त्वाचे!): NARR लहाजा कोल्हापुरी ग्रामीण बोलभाषेत लिहा — जणू गावातील मुलगी मित्राला समजावते; दामा ठेवा ('असतं', 'करं', 'मग', 'का', 'बरं', 'राव'). आशय अचूक रहावा. बुलेट्स मात्र प्रमाणभाषेत — स्वच्छ व छोटे."

def groq_script_2stage(topic, ground, nsec, outdir, dialect="", lang="mr", seed=None):
    """Returns script dict on success, None on any failure (caller falls back)."""
    gk = os.environ.get("GROQ_KEY")
    if not gk:
        return None
    chat = make_chat(gk)

    hi = (lang == "hinglish")
    tplA = PROMPT_A_HI if hi else PROMPT_A_TPL
    seed_block = ''
    if hi and seed:
        seed_block = ("\n\nAaj ka CENTERPIECE — MPSC modern-history SAWAAL (Marathi mein diya gaya): '" + seed.get('question', '')
                      + "' | Sahi jawaab: " + seed.get('answer_letter', '') + " — " + seed.get('answer', '')
                      + " | Marathi explanation: " + seed.get('explanation', '')
                      + "\nIMPORTANT: POORA film HINGLISH mein — Devanagari Hindi + English words. Koi Marathi word NAHI (titles/headings/bullets sab Hinglish). Filmon ka title sirf Hinglish mein. TITLE line zaroor do."
                      + "\nTITLE rule: TITLE mein SAHI JAWAAB wala asli naam/fact ZAROOR ho ('" + seed.get('answer', '') + "' — jaisa likha hai waisa hi; gender/role/title apni taraf se MAT badlo). Title catchy ho sakta hai par FACT accurate raho — sirf seed ke facts use karo, koi imagined fact nahi.")
    dia = (DIA_A if dialect == "kolhapuri" else "") if not hi else ""   # dialect = Marathi-only feature
    A = chat(tplA.format(topic=topic, ground=ground[:1600], nsec=nsec) + dia + seed_block, mx=2200,
             sysmsg=(SYS_HI if hi else SYS))
    if not A:
        say("stageA empty")
        return None
    film_title = _grab(r"^TITLE:\s*(.+)$", A)
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
        tplB = PROMPT_B_HI if hi else PROMPT_B_TPL
        B = chat(tplB.format(topic=topic, i=i + 1, total=len(outs),
                             heading=ch["heading"], kind=ch["kind"],
                             ground=ground[:1200]) + ((DIA_B if dialect == "kolhapuri" else "") if not hi else ""), mx=900,
                 sysmsg=(SYS_HI if hi else SYS))
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
          "film_title": film_title,
          "hook": hook or (("Namaskar doston! Aaj hum detail mein samjhenge — " + topic) if hi else ("नमस्कार! आज आपण " + topic + " हा विषय सविस्तर समजून घेणार आहोत.")),
          "chapters": done,
          "recap": recap or ((topic + " — main points revise karo, notes likho.") if hi else (topic + " — मुख्य मुद्दे पुन्हा पाहा आणि नोट्स करा.")),
          "cta": cta or (("Mmindpower Subscribe karo aur Telegram @mmindpower_1 par roz practice karo!") if hi else "Subscribe करा आणि टेलिग्रामवर @mmindpower_1 मध्ये रोज सराव करा.")}
    say("groq 2-stage script OK — {} chapters".format(len(done)))
    return sc


def quiz_hinglish(seed):
    """Translate the seed bank-question into film Hinglish (order of options preserved).
    Returns {'q_hi', 'options_hi', 'explain_hi'} or None on any failure."""
    gk = os.environ.get("GROQ_KEY")
    if not gk or not seed:
        return None
    opts = seed.get("options") or []
    if len(opts) < 4:
        return None
    optline = " | ".join("{} ) {}".format("ABCD"[i], o) for i, o in enumerate(opts[:4]))
    user = ("Is MPSC question ko student-friendly HINGLISH mein dubara likho "
            "(Devanagari Hindi + English words naturally mixed; Marathi grammar words bilkul nahi). "
            "Options ka ORDER exactly SAME rakho.\n\n"
            "Question (Marathi): " + seed.get("question", "") + "\n"
            "Options: " + optline + "\n"
            "Sahi jawaab: " + seed.get("answer", "") + "\n"
            "Explanation (Marathi): " + seed.get("explanation", "") + "\n\n"
            "Sirf YA 3 lines do — kuch aur nahi:\n"
            "Q: <sawaal Hinglish mein>\n"
            "O: A) <opt> | B) <opt> | C) <opt> | D) <opt>\n"
            "EX: <1-2 vaakya explanation Hinglish mein — kyon ye jawaab sahi hai>")
    txt = make_chat(gk)(user, temp=0.3, mx=900, sysmsg=SYS_HI)
    if not txt:
        return None
    q_hi = _grab(r"^Q:\s*(.+)$", txt)
    o_line = _grab(r"^O:\s*(.+)$", txt)
    ex = _grab(r"^EX:\s*(.+)$", txt)
    o_hi = [re.sub(r"^[A-D]\s*[).:\-]\s*", "", p.strip()).strip() for p in o_line.split("|")] if o_line else []
    if not q_hi or len(o_hi) != 4:
        say("quiz_hinglish parse fail (q=%s opts=%d)" % (bool(q_hi), len(o_hi)))
        return None
    return {"q_hi": q_hi, "options_hi": o_hi, "explain_hi": ex}
