#!/usr/bin/env python3
"""tools/wiki_ground.py — Wikipedia grounding + logging for the question bank factory.

Carved out of the retired video_explainer.py so the bank pipeline keeps working
after the film workflows were deleted. Only two things are needed there:
`say()` for timestamped log lines and `wiki_ground()` for a grounded snippet.
"""
import time

UA = {"User-Agent": "MmindpowerExplainer/1.0 (educational open-content use)"}


def say(m):
    print(time.strftime("[%H:%M:%S]"), m, flush=True)


def wiki_ground(topic):
    """Search -> best title -> REST summary (never silently empty: always narrates its path)."""
    import requests
    for lang in ("mr", "en"):
        try:
            sr = requests.get(f"https://{lang}.wikipedia.org/w/api.php",
                              params={"action": "opensearch", "search": topic, "limit": 3,
                                      "namespace": 0, "format": "json"}, headers=UA, timeout=30)
            hits = sr.json()[1] if isinstance(sr.json(), list) else []
            say(f"wiki[{lang}] search hits: {hits[:2]}")
            for title in hits[:2] or [topic]:
                try:
                    sm = requests.get(f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{requests.utils.quote(title)}",
                                      headers=UA, timeout=30)
                    if sm.status_code == 200:
                        txt = (sm.json().get("extract") or "").strip()
                        if len(txt) > 150:
                            say(f"wiki[{lang}] grounded via '{title}': {len(txt)} chars")
                            return txt[:3500]
                except Exception as e:
                    say(f"wiki[{lang}] summary err: {str(e)[:60]}")
        except Exception as e:
            say(f"wiki[{lang}] search skip: {str(e)[:60]}")
    say("wiki: no grounding found (continuing with model knowledge only)")
    return ""
