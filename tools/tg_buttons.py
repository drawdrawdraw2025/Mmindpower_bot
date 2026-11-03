#!/usr/bin/env python3
"""Attach Skip-Intro / Jump-to-Question inline buttons to a channel film post.

Usage: tg_buttons.py <bot_token> <chat_id> <film_msg_id> <quiz_msg_id|-> <body_msg_id|->
"""
import json
import sys
import urllib.request


def main():
    tok, ch = sys.argv[1], sys.argv[2]
    fm, qm, bm = sys.argv[3], sys.argv[4], sys.argv[5]
    rows = []
    if bm not in ("", "-"):
        rows.append([{"text": "⏭ 1 · Skip Intro — seedha content se shuru",
                      "url": f"https://t.me/mmindpower_1/{bm}"}])
    if qm not in ("", "-"):
        rows.append([{"text": "🎯 2 · Jump to the Question — quiz bite",
                      "url": f"https://t.me/mmindpower_1/{qm}"}])
    if not rows or fm in ("", "-"):
        print("tg_buttons: nothing to attach")
        return
    body = json.dumps({"chat_id": ch, "message_id": int(fm),
                       "reply_markup": {"inline_keyboard": rows}}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{tok}/editMessageReplyMarkup",
        data=body, headers={"Content-Type": "application/json"})
    try:
        resp = urllib.request.urlopen(req, timeout=30).read()[:200]
        print("buttons set:", resp)
    except Exception as e:
        print("button edit failed:", e)


if __name__ == "__main__":
    main()
