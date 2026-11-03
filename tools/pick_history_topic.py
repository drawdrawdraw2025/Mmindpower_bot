# tools/pick_history_topic.py — today's modern-history seed question from our own bank (day-rotated)
import json, glob, datetime, os, sys

KEYS = ["इतिहास", "1857", "1942", "स्वातंत्र्य", "क्रांती", "चळवळ", "काँग्रेस", "आंबेडकर", "फुले",
        "शिवाजी", "मराठीट", "मराठा", "झांसी", "नेहरू", "गांधी", "सत्याग्रह", "आंदोलन", "ब्रिटिश",
        "क्विट", "सुभाष", "लोकमान्य", "दादाभाई", "बंगाल", "विभाजन", "दंडी", "गोलमेज", "साइमन",
        "क्रिप्स", "गवर्नर", "ऐतिहासिक", "पेशवे", "संस्थान", "अकबर", "औरंगजेब", "वसई", "सातारा", "कट"]

BAD_LEADS = ("जोड्या लावा", "विधाने विचारात", "कालक्रमानुसार", "कालक्रम लावा", "जोड्या जुळवा", "क्रमाने मांडा", "कोष्टक", "त्यांत्र")

def film_worthy(q):
    qm = (q.get("q_marathi") or "").strip()
    exp = (q.get("explanation_marathi") or "").strip()
    if not (25 <= len(qm) <= 180): return False
    if any(b in qm for b in BAD_LEADS): return False
    if len(exp) < 40: return False
    return True

def pool():
    hits = []
    for fp in sorted(glob.glob("quiz_data_*.json"), key=lambda p: (len(p), p)):
        try:
            for q in json.load(open(fp, encoding="utf-8")):
                blob = (q.get("q_marathi", "") + " " + str(q.get("subtopic", "")) + " " + q.get("explanation_marathi", ""))
                if any(k in blob for k in KEYS) and film_worthy(q):
                    hits.append(q)
        except Exception:
            pass
    return hits

def pick():
    ps = pool()
    assert ps, "no history questions found"
    doy = datetime.date.today().timetuple().tm_yday
    q = ps[(doy - 1) % len(ps)]
    ci = q.get("correct_index", 0)
    if isinstance(ci, str):
        ci = ci.strip(); ci = ord(ci) - 65 if ci.isalpha() else int(ci)
    opts = q.get("options", [])
    if isinstance(opts, str):
        import ast
        try: opts = list(ast.literal_eval(opts))
        except Exception: opts = [x.strip() for x in opts.strip("[]").split(",")]
    return {
        "question": q.get("q_marathi", "").strip(),
        "options": opts[:4],
        "answer": (opts[ci] if opts and isinstance(ci, int) and 0 <= ci < len(opts) else ""),
        "answer_letter": ("ABCD"[ci] if isinstance(ci, int) and 0 <= ci < 4 else "A"),
        "explanation": (q.get("explanation_marathi") or "").strip(),
        "subtopic": str(q.get("subtopic", "")).strip(),
    }, len(ps)

if __name__ == "__main__":
    outdir = sys.argv[1] if len(sys.argv) > 1 else "out_explainer"
    os.makedirs(outdir, exist_ok=True)
    seed, n = pick()
    fp = os.path.join(outdir, "day_seed.json")
    json.dump(seed, open(fp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"history pool={n} | seed → {fp}")
    print("SEED Q:", seed["question"][:120], "| ANS:", seed["answer"][:50])
