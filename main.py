#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Twitter Daily Poster
- Posts exactly one tweet when launched (use OS scheduler to run daily)
- Reads the next idea from content/ideas_ru.txt (one idea per line)
- Tracks progress in data/state.json
- If the ideas file runs out, it will reshuffle and start again
- Supports optional daily time gating (RUN_WINDOW_START / RUN_WINDOW_END) to avoid accidental multiple posts

Requirements: tweepy, python-dotenv, pytz
"""

import os
import json
import random
import time
from datetime import datetime
from pathlib import Path

import tweepy
from dotenv import load_dotenv
import pytz

ROOT = Path(__file__).resolve().parent
CONTENT_FILE = ROOT / "content" / "ideas_ru.txt"
STATE_FILE = ROOT / "data" / "state.json"

def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"index": 0, "order": [], "last_posted_at": None}

def save_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

def load_ideas():
    if not CONTENT_FILE.exists():
        raise FileNotFoundError(f"Не найден файл с идеями: {CONTENT_FILE}")
    ideas = [line.strip() for line in CONTENT_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not ideas:
        raise ValueError("Файл ideas_ru.txt пуст. Добавьте туда идеи (по одной в строке).")
    return ideas

def ensure_order(state, n):
    order = state.get("order") or []
    # regenerate if empty or invalid
    if not order or any(i >= n for i in order):
        order = list(range(n))
        random.shuffle(order)
        state["order"] = order
        state["index"] = 0
    return order

def within_run_window(tzname, start_hm, end_hm):
    """
    Optional: only post if current local time is within [start_hm, end_hm).
    tzname like 'Europe/Riga'
    start_hm and end_hm like '09:00'
    """
    if not (tzname and start_hm and end_hm):
        return True  # no gating
    try:
        tz = pytz.timezone(tzname)
        now = datetime.now(tz)
        sh, sm = map(int, start_hm.split(":"))
        eh, em = map(int, end_hm.split(":"))
        start = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
        end = now.replace(hour=eh, minute=em, second=0, microsecond=0)
        if end <= start:
            # window wraps past midnight
            return (now >= start) or (now < end)
        else:
            return (now >= start) and (now < end)
    except Exception:
        return True

def trim_to_limit(text, limit=280):
    if len(text) <= limit:
        return text
    # Soft trim at last space before limit
    cutoff = text[:limit]
    if " " in cutoff:
        cutoff = cutoff[:cutoff.rfind(" ")]
    return cutoff[:limit-1] + "…"

def build_tweet(raw_text, tzname):
    # Add optional date hashtag or signature per env
    add_date = os.getenv("ADD_DATE", "true").lower() in ("1", "true", "yes", "y")
    add_hashtag = os.getenv("ADD_HASHTAG", "").strip()
    tz = pytz.timezone(tzname) if tzname else pytz.utc
    today = datetime.now(tz).strftime("%Y-%m-%d")
    parts = [raw_text]
    if add_date:
        parts.append(f"\n\n{today}")
    if add_hashtag:
        parts.append(f" #{add_hashtag}")
    text = "".join(parts).strip()
    return trim_to_limit(text)

def post_tweet(text):
    # Auth via OAuth 1.0a (requires Elevated write access on X API)
    api_key = os.getenv("TWITTER_API_KEY") or os.getenv("X_API_KEY")
    api_secret = os.getenv("TWITTER_API_SECRET") or os.getenv("X_API_SECRET")
    access_token = os.getenv("TWITTER_ACCESS_TOKEN") or os.getenv("X_ACCESS_TOKEN")
    access_secret = os.getenv("TWITTER_ACCESS_SECRET") or os.getenv("X_ACCESS_SECRET")

    if not all([api_key, api_secret, access_token, access_secret]):
        raise RuntimeError("Не заданы ключи API. Заполните .env (TWITTER_*/X_*).")

    auth = tweepy.OAuth1UserHandler(api_key, api_secret, access_token, access_secret)
    api = tweepy.API(auth)
    # v1.1 endpoint
    api.update_status(status=text)

def main():
    load_dotenv(dotenv_path=ROOT / ".env")

    topic = os.getenv("TOPIC", "").strip()
    tzname = os.getenv("TIMEZONE", "Europe/Riga")
    start_hm = os.getenv("RUN_WINDOW_START", "")  # e.g. "09:00"
    end_hm = os.getenv("RUN_WINDOW_END", "")      # e.g. "12:00"

    if not within_run_window(tzname, start_hm, end_hm):
        print("Вне заданного окна запуска — публикация пропущена.")
        return

    ideas = load_ideas()
    state = load_state()
    ensure_order(state, len(ideas))

    idx = state.get("index", 0)
    order = state["order"]
    if idx >= len(order):
        # reshuffle if completed
        random.shuffle(order)
        state["order"] = order
        idx = 0

    idea_index = order[idx]
    raw_text = ideas[idea_index]
    if topic and "{topic}" in raw_text:
        raw_text = raw_text.replace("{topic}", topic)

    tweet = build_tweet(raw_text, tzname)

    # Post
    post_tweet(tweet)

    # Update state
    state["index"] = idx + 1
    state["last_posted_at"] = datetime.utcnow().isoformat() + "Z"
    save_state(state)

    print("Опубликовано:", tweet)

if __name__ == "__main__":
    main()
