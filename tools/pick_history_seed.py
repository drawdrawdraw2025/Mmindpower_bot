# tools/pick_history_seed.py — films lane = modern-history questions from our own bank ONLY
# Writes out_explainer/history_seed.json for video_explainer.py --seed-file
import json, glob, os, datetime, argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out_explainer")

# strictly MODERN era (1800s → 1947 + national movement); excludes medieval/maratha-empire bleed
# non-history items whose text collides with history keywords (विभाजन-cell-division, years in science)
EXCLUDE = ["enzyme", "antigen", "antibod", "immun", "हायब्रिडोमा", "मायलोमा", "प्रोटीन", "quantum",
           "क्लायमेट", "प्रदूषण", "नुक्लि", "औषध", "रसायन", "physics", "chemistry", "biology",
           "cell biology", "virus", "व्हायरस", "डाऊन सिंड्रोम", "जीन्स", "metabol"]
MODERN = ["1857","1858","1885","1905","1911","1915","1916","1917","1918","1919","1920","1921","1922","1924","1925","1927","1928","1929","1930","1931","1932","1935","1939","1940","1942","1943","1945","1946","1947",
          "स्वातंत्र्य","काँग्रेस","ब्रिटिश","क्रांतीक","सत्याग्रह","दंडी","गांधी","नेहरू","जिन्ना","आंबेडकर","टिळक","सावरकर","सुभाष","भागत","चंद्रशेखर","अशफाक","लोकमान्य","गोखले","रमाबाई","क्रांतिगुरू","मुस्लिम लीग","हिंदू महासभा","घर चळवळ","बहिष्कार","विभाजन","गोलमेज","साइमन","क्रिप्स","कॅबिनेट","वायसरॉय","गवर्नर जनरल","ला~होर","रक्तक्रांती","चले जाव","स्वराज","छोडो","बोर्ड","अधिनियम","कायदा","कम्युनल अवॉर्ड","पूना पॅक्ट","मोंटेग्यू","मोरले","ऑगस्ट ऑफर","रेडक्लिफ","स्वतंत्र्य दिन","राष्ट्रपिता","असहकार","जलियनवाला","रौलॅट","वॅव्हेल","माउंटबॅटन","पायनिअर","मदन मोहन मालवीय"]

FALLBACK = [  # if bank yields fewer than MIN bank hits (never fires with 400+ but is the safety net)
    "1857 CHA UTHAAV — Indians ki pehli badi ladai",
    "Indian National Congress ki sthapana (1885) aur udaarwaad ka daur",
    "1905 Bengal vivajan aur swadeshi andolan",
    "Gandhi ji ka Champaran satyagraha (1917)",
    "Jallianwala Bagh nar-sanhar (1919)",
    "Asahakaar aur Khilafat andolan (1920-22)",
    "Simon Commission ka bahishkaar (1928)",
    "Dandi yaatra aur lavana satyagraha (1930)",
    "Golmej conference aur Poona Pact (1932)",
    "Government of India Act 1935",
    "Quit India — 'Chale Jaav' andolan (1942)",
    "Subhash Chandra Bose aur Azad Hind Fauj",
    "Cabinet Mission Plan (1946)",
    "Mountbatten Plan aur Bharat vibhajan (1947)",
    "Azadi ka pahla swatantrya din (15 Aug 1947)",
]

def modern_hits():
    seen, out = set(), []
    for fp in sorted(glob.glob(os.path.join(ROOT, "quiz_data_*.json")), key=lambda p: (len(p), p)):
        try:
            for q in json.load(open(fp, encoding="utf-8")):
                blob = (q.get("q_marathi", "") + " " + q.get("subtopic", "") + " " + q.get("explanation_marathi", ""))
                if any(x in blob.lower() for x in EXCLUDE):
                    continue
                if any(k in blob for k in MODERN):
                    key = (q.get("q_marathi", "") or "")[:70]
                    if key and key not in seen:
                        seen.add(key)
                        out.append(q)
        except Exception:
            pass
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(OUT, "history_seed.json"))
    a = ap.parse_args()
    hits = modern_hits()
    print(f"[seed picker] bank modern-history questions: {len(hits)}")
    doy = datetime.date.today().timetuple().tm_yday
    if hits:
        q = hits[(doy - 1) % len(hits)]
        ci = q.get("correct_index", 0)
        opts = q.get("options", [])
        ans = opts[ci] if isinstance(ci, int) and ci < len(opts) else (opts[0] if opts else "")
        seed = {
            "topic": f"Modern History: {(q.get('subtopic') or 'Bharatiya swatantrya sangharsh')[:60]}",
            "question": q.get("q_marathi", ""),
            "answer": ans,
            "explanation": q.get("explanation_marathi", "")[:400],
            "source": "bank",
            "doy_index": (doy - 1) % len(hits), "pool": len(hits),
        }
    else:
        t = FALLBACK[(doy - 1) % len(FALLBACK)]
        seed = {"topic": t, "question": "", "answer": "", "explanation": "", "source": "fallback_list"}
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    json.dump(seed, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"[seed picker] TODAY → {seed['topic']}  (src={seed['source']} #{seed.get('doy_index',0)}/{seed.get('pool', len(FALLBACK))})")
    print(f"[seed picker] Q: {seed['question'][:100]}")

if __name__ == "__main__":
    main()
