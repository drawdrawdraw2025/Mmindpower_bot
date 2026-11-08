#!/usr/bin/env python3
"""tools/check_bank.py — audit every quiz_data_*.json before it can ship.

Why this exists: a whole series of auto-generated sets (quiz_data_F<yymmdd>, 151
questions) once reached production and could not be answered, because a set name
with digits breaks qid round-tripping ("F261104" + index 5 -> "F2611046" ->
parsed as set "F", index 2611045 -> get_q() returns None). Every tap then
rendered as option A. This script makes that class of bug impossible to commit.

Usage:
    python3 tools/check_bank.py            # human summary, exit 1 on any error
    python3 tools/check_bank.py --json     # machine-readable report

Errors block CI. Warnings never do — they are things to look at, not reasons to
stop the 06:45 IST bank run.
"""
import argparse
import glob
import json
import os
import re
import sys
import unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

REQUIRED = ("subtopic", "qtype", "q_marathi", "options", "correct_index",
            "explanation_marathi", "evidence")
SET_NAME_RE = re.compile(r"^[A-Z]+$")          # bot.builds qid as f"{set}{index+1}"
QID_RE = re.compile(r"^([A-Z]+)(\d+)$")        # bot.parse_qid
LETTERS = "ABCD"

# Thresholds for warnings (never errors)
LONG_Q_CHARS = 350        # bot.qotd_post skips these when picking the public QOTD
SKEW_WARN = 0.70          # a single option key over this share is guessable
SET_SIZE = 90


def canon(text):
    """Same normalisation the bank factory uses to spot duplicates."""
    s = unicodedata.normalize("NFKC", text or "")
    return re.sub(r"[\s।.,?\-—()\"]+", "", s)[:120]


def qid_of(set_letter, index):
    return f"{set_letter}{index + 1}"


def qid_parses(set_letter, index):
    """True only if qid_of() round-trips through the bot's parser."""
    m = QID_RE.match(qid_of(set_letter, index))
    if not m:
        return False
    return m.group(1) == set_letter and int(m.group(2)) - 1 == index


def audit(path):
    """Return (errors, warnings, stats) for one quiz_data_*.json file."""
    name = os.path.basename(path)
    sid = name[len("quiz_data_"):-len(".json")]
    errors, warnings = [], []
    stats = {"set": sid, "file": name, "questions": 0, "keys": {}}

    if not SET_NAME_RE.match(sid):
        errors.append(f"{name}: set name '{sid}' must be A-Z only — a digit makes "
                      f"every qid unparseable (this is the retired F26 bug)")
    try:
        rows = json.load(open(path, encoding="utf-8"))
    except Exception as e:
        return [f"{name}: invalid JSON — {e}"], [], stats
    if not isinstance(rows, list):
        return [f"{name}: top level must be a JSON list, got {type(rows).__name__}"], [], stats
    if not rows:
        errors.append(f"{name}: set is empty")
        return errors, warnings, stats

    stats["questions"] = len(rows)
    keys = {}
    for i, q in enumerate(rows):
        where = f"{name}[{i}] (qid {qid_of(sid, i)})"
        if not isinstance(q, dict):
            errors.append(f"{where}: row is not an object")
            continue

        for k in REQUIRED:
            if k not in q:
                errors.append(f"{where}: missing key '{k}'")

        qm = q.get("q_marathi")
        if not isinstance(qm, str) or not qm.strip():
            errors.append(f"{where}: q_marathi is empty or not text")
        elif len(qm.strip()) < 15:
            errors.append(f"{where}: q_marathi too short ({len(qm.strip())} chars)")
        else:
            k = canon(qm)
            if k in keys:
                errors.append(f"{where}: duplicate question — same text as {keys[k]}")
            else:
                keys[k] = qid_of(sid, i)

        opts = q.get("options")
        if not isinstance(opts, list):
            errors.append(f"{where}: options must be a list")
        else:
            if len(opts) != 4:
                errors.append(f"{where}: exactly 4 options required, found {len(opts)}")
            for j, o in enumerate(opts):
                if not isinstance(o, str) or not o.strip():
                    errors.append(f"{where}: option {'ABCD'[j] if j < 4 else j} is empty or not text")

        ci = q.get("correct_index")
        if not isinstance(ci, int) or isinstance(ci, bool):
            errors.append(f"{where}: correct_index must be an int, got {type(ci).__name__}")
        elif not 0 <= ci < 4:
            errors.append(f"{where}: correct_index {ci} outside 0-3")
        else:
            keys.setdefault("_", None)
            stats["keys"][LETTERS[ci]] = stats["keys"].get(LETTERS[ci], 0) + 1

        if i == 0 and not qid_parses(sid, 0):
            errors.append(f"{name}: qid round-trip broken — '{qid_of(sid, 0)}' does not "
                          f"parse back to ('{sid}', 0)")
            break                      # one report per file is enough

    # ---- warnings: typed, so main() can aggregate instead of spamming ----
    if len(rows) < SET_SIZE:
        warnings.append({"kind": "short_set", "set": sid, "n": len(rows)})
    no_en = sum(1 for q in rows if isinstance(q, dict) and not (q.get("q_english") or "").strip())
    if no_en:
        warnings.append({"kind": "no_english", "set": sid, "n": no_en})
    long_q = sum(1 for q in rows if isinstance(q, dict)
                 and len((q.get("q_marathi") or "")) > LONG_Q_CHARS)
    if long_q:
        warnings.append({"kind": "long", "set": sid, "n": long_q})
    total = sum(stats["keys"].values())
    if total >= 20:
        top = max(stats["keys"].items(), key=lambda kv: kv[1])
        if top[1] / total > SKEW_WARN:
            warnings.append({"kind": "skew", "set": sid, "letter": top[0],
                             "n": top[1], "total": total})
    return errors, warnings, stats


def main():
    ap = argparse.ArgumentParser(description="Audit the MCQ bank before it ships.")
    ap.add_argument("--json", action="store_true", help="emit a JSON report")
    ap.add_argument("--dir", default=ROOT, help="repo root (default: parent of tools/)")
    args = ap.parse_args()

    files = sorted(glob.glob(os.path.join(args.dir, "quiz_data_*.json")),
                   key=lambda p: (len(p), p))
    if not files:
        print("check_bank: no quiz_data_*.json files found", file=sys.stderr)
        return 1

    errors, warnings, stats, bank_keys = [], [], [], {}
    for f in files:
        e, w, st = audit(f)
        errors += e
        warnings += w
        stats.append(st)
        for k, v in st["keys"].items():
            bank_keys[k] = bank_keys.get(k, 0) + v

    total_q = sum(s["questions"] for s in stats)
    grand = sum(bank_keys.values())
    skew = {}
    if grand:
        skew = {k: round(v * 100 / grand, 1) for k, v in sorted(bank_keys.items())}
        top_k = max(bank_keys.items(), key=lambda kv: kv[1])
        if top_k[1] / grand > SKEW_WARN:
            warnings.append({"kind": "bank_skew", "letter": top_k[0],
                             "n": top_k[1], "total": grand})

    # aggregate the noise into one short line per category
    lines = []
    bad_sets = [w for w in warnings if w["kind"] == "skew"]
    if bad_sets:
        worst = sorted(bad_sets, key=lambda w: -w["n"] / w["total"])[:5]
        shown = ", ".join(f"{w['set']} {w['letter']}={w['n'] * 100 // w['total']}%" for w in worst)
        more = "" if len(bad_sets) <= 5 else f" (+{len(bad_sets) - 5} more)"
        lines.append(f"⚠️  {len(bad_sets)} set(s) have a guessable answer key: {shown}{more}")
    for w in warnings:
        if w["kind"] == "bank_skew":
            lines.append(f"⚠️  bank-wide answer key {w['letter']} = {w['n']}/{w['total']} "
                         f"({w['n'] * 100 // w['total']}%) — a pure guesser scores that much")
    notes = []
    n_long = sum(w["n"] for w in warnings if w["kind"] == "long")
    if n_long:
        notes.append(f"{n_long} question(s) over {LONG_Q_CHARS} chars (excluded from the public QOTD pick)")
    n_noen = sum(w["n"] for w in warnings if w["kind"] == "no_english")
    if n_noen:
        notes.append(f"{n_noen} without q_english")
    short = [w for w in warnings if w["kind"] == "short_set"]
    if short:
        notes.append("below " + str(SET_SIZE) + ": "
                     + ", ".join(f"{w['set']} {w['n']}" for w in short))

    if args.json:
        print(json.dumps({"ok": not errors, "sets": len(files), "questions": total_q,
                          "answer_keys": skew, "errors": errors,
                          "warnings": warnings}, ensure_ascii=False, indent=2))
    else:
        print(f"check_bank: {len(files)} sets · {total_q} questions")
        if grand:
            print("  answer key: " + "  ".join(f"{k} {v}%" for k, v in skew.items()))
        for ln in lines:
            print("  " + ln)
        if notes:
            print("  ℹ️  " + "; ".join(notes))
        for e in errors:
            print(f"  ❌  {e}")
        print("RESULT:", "FAIL — fix the errors above" if errors else "PASS ✓")

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
