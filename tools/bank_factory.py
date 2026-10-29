# tools/bank_factory.py — grows the MCQ bank daily, line-protocol Groq + Wikipedia grounding
# Provenance: new questions land in quiz_data_F<yymmdd>.json with EXACT legacy shape
# (options as repr-string, correct_index as string) so every existing consumer stays safe.
import os, re, json, glob, datetime, unicodedata
from video_explainer import wiki_ground, say
from groq2stage import make_chat

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PROMPT = """MPSC स्पर्धा-परीक्षा स्तरावर विषय "{topic}" बद्दल अगदी {n} नवीन बहुपर्यायी प्रश्न लिहा — सर्व मराठीत.

संदर्भ (विकिपीडिया, फक्त भीतरले तथ्य वापरा — तारखा/नावे/आकडे इतरत्र न घेता):
{ground}

नियम:
- प्रत्येक प्रश्नाचे खालील 4 ओळी (इतर काहीही नाही, कुंपण नाही):
Q: <प्रश्न, एक ओळ, मराठी>
A: <पर्याय1> | <पर्याय2> | <पर्याय3> | <पर्याय4>
ANS: <1 किंवा 2 किंवा 3 किंवा 4>
WHY: <एक ओळीचं स्पष्टीकरण, मराठी, तथ्यासह>
- पर्याय प्रामाणिक असावेत (उत्तर एकदोन्ही ओळींनी स्पष्ट), अशुद्ध पर्याय पुढेसारखे, पण स्पष्टपणे चुकीचे
- इंग्रजी शब्द टाळा; तंत्र-संज्ञा असल्यास ( ) मध्ये इंग्रजी टिपणी घालू शकता
"""


def _canon(s):
    s = unicodedata.normalize("NFKC", s or "")
    return re.sub(r"[\s।.,?\-—()]+", "", s)


def existing_canon():
    seen = set()
    for fp in glob.glob(os.path.join(ROOT, "quiz_data_*.json")):
        try:
            for q in json.load(open(fp, encoding="utf-8")):
                seen.add(_canon(q.get("q_marathi", ""))[:80])
        except Exception:
            pass
    say(f"bank fingerprint pool: {len(seen)}")
    return seen


def parse_items(txt, topic, wtitle):
    """Strict per-block extraction; returns list of validated question dicts (legacy shape)."""
    out = []
    blocks = re.findall(
        r"Q:\s*(.+?)\s*\nA:\s*(.+?)\s*\nANS:\s*([1-4])\s*\nWHY:\s*(.+?)(?=\n\s*Q:|\Z)", txt, re.S)
    for q, opts_raw, ans, why in blocks:
        opts = [o.strip() for o in re.split(r"[|｜]", opts_raw) if o.strip()]
        q = re.sub(r"\s+", " ", q).strip()
        why = re.sub(r"\s+", " ", why).strip()
        if not (30 <= len(q) <= 220):
            continue
        if len(opts) != 4 or any(len(o) > 90 for o in opts):
            continue
        if len(why) < 20:
            continue
        out.append({
            "section": "F",
            "subtopic": topic,
            "qtype": "direct",
            "q_marathi": q,
            "q_english": "",
            "options": opts,                     # real list — matches all 2,663 rows
            "correct_index": int(ans) - 1,       # int, 0-based — matches all consumers
            "explanation_marathi": why,
            "evidence": "Wikipedia-mr: " + (wtitle or "n/a") + " · auto-factory",
        })
    return out


def grow(target=40, topics_per_run=4):
    gk = os.environ.get("GROQ_KEY")
    if not gk:
        raise SystemExit("GROQ_KEY missing")
    chat = make_chat(gk)
    bank = [l.strip() for l in open(os.path.join(ROOT, "topics_bank.txt"), encoding="utf-8") if l.strip()]
    doy = datetime.date.today().timetuple().tm_yday
    todays = [bank[(doy + 2 + i) % len(bank)] for i in range(topics_per_run)]
    say(f"today's bank topics: {todays}")
    seen = existing_canon()
    per = max(4, target // topics_per_run)
    fresh, wiki_used = [], []
    for t in todays:
        ground = wiki_ground(t)
        if not ground:
            say(f"[skip] no wiki ground for: {t}")
            continue
        wtitle = t                                   # evidence uses topic label
        wiki_used.append(wtitle)
        got = 0
        for attempt in range(2):
            r = chat(PROMPT.format(topic=t, n=per, ground=ground[:1500]), mx=2200)
            if not r:
                break
            items = parse_items(r, t, wtitle)
            for it in items:
                key = _canon(it["q_marathi"])[:80]
                if key in seen:
                    continue
                seen.add(key)
                fresh.append(it)
            got = len(items)
            if got >= per // 2 or fresh and len(fresh) >= target:
                break
        say(f"[{t}] +{got} raw → bank +{sum(1 for f in fresh if f['subtopic'] == t)}")
    if not fresh:
        say("nothing new today — bank clean")
        return 0, ""
    d = datetime.date.today().strftime("%y%m%d")
    fp = os.path.join(ROOT, f"quiz_data_F{d}.json")
    # merge with any same-day existing file to avoid overwrite on rerun
    if os.path.exists(fp):
        old = json.load(open(fp, encoding="utf-8"))
        old_keys = {_canon(q.get("q_marathi", ""))[:80] for q in old}
        fresh = [f for f in fresh if _canon(f["q_marathi"])[:80] not in old_keys]
        data = old + fresh
    else:
        data = fresh
    json.dump(data, open(fp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    say(f"BANK GROWN: +{len(fresh)} new MCQs → {os.path.basename(fp)} (file size {len(data)})")
    return len(fresh), os.path.basename(fp)


if __name__ == "__main__":
    import sys
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    grow(target=n)
