import os
import re
import json
import hashlib
import difflib
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup
from openai import OpenAI

ROOT = Path(__file__).resolve().parent
TARGETS_FILE = ROOT / "targets.json"
SNAPSHOTS_FILE = ROOT / "storage" / "snapshots.json"

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TEST_NOTIFICATION = os.getenv("TEST_NOTIFICATION", "0") == "1"

USER_AGENT = (
    "Mozilla/5.0 (compatible; ChangeMonitorAgent/0.1; "
    "+https://github.com/)"
)

MAX_TEXT_CHARS = 50_000
MAX_DIFF_CHARS = 14_000


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def normalize_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

    text = soup.get_text("\n")
    lines = []

    for line in text.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            lines.append(line)

    return "\n".join(lines)[:MAX_TEXT_CHARS]


def fetch_target(url: str) -> str:
    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=30,
        allow_redirects=True,
    )
    response.raise_for_status()
    return normalize_text(response.text)


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def make_diff(old: str, new: str) -> str:
    diff = difflib.unified_diff(
        old.splitlines(),
        new.splitlines(),
        fromfile="before",
        tofile="after",
        lineterm="",
        n=2,
    )
    return "\n".join(diff)[:MAX_DIFF_CHARS]


def extract_json(text: str) -> dict:
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("Model response did not contain JSON.")

    return json.loads(match.group(0))


def analyze_change(target: dict, diff: str) -> dict:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is missing.")

    client = OpenAI(api_key=OPENAI_API_KEY)

    keywords = ", ".join(target.get("keywords", [])) or "none"
    context = target.get("context", "")

    prompt = f"""
You are a webpage change-monitoring agent.

Target name: {target.get("name", "Unknown")}
Target URL: {target.get("url", "")}
User keywords/interests: {keywords}
Extra context: {context}

Your job:
1. Ignore cosmetic, navigation, timestamp, footer, ad, tracking, and layout-only changes.
2. Decide whether the actual content change matters to the user's stated interests.
3. Score relevance from 0 to 10.
4. Summarize the meaningful change in Persian, briefly and concretely.
5. Return ONLY valid JSON with this exact shape:

{{
  "relevant": true,
  "score": 0,
  "title": "short Persian title",
  "summary": "short Persian summary",
  "reason": "short Persian reason"
}}

Observed diff:
--- BEGIN DIFF ---
{diff}
--- END DIFF ---
""".strip()

    response = client.responses.create(
        model=OPENAI_MODEL,
        input=prompt,
    )

    result = extract_json(response.output_text)
    result["score"] = int(result.get("score", 0))
    result["relevant"] = bool(result.get("relevant", False))
    return result


def telegram_send(message: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError("Telegram secrets are missing.")

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    response = requests.post(
        url,
        json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "disable_web_page_preview": True,
        },
        timeout=30,
    )
    response.raise_for_status()


def format_alert(target: dict, result: dict) -> str:
    score = result.get("score", 0)
    return (
        "🔔 تغییر مهم شناسایی شد\n\n"
        f"منبع: {target.get('name', 'Unknown')}\n"
        f"امتیاز اهمیت: {score}/10\n"
        f"عنوان: {result.get('title', '—')}\n\n"
        f"{result.get('summary', '')}\n\n"
        f"دلیل: {result.get('reason', '')}\n\n"
        f"لینک: {target.get('url', '')}"
    )


def run() -> None:
    config = load_json(TARGETS_FILE, {"targets": []})
    snapshots = load_json(SNAPSHOTS_FILE, {})
    changed_snapshots = False

    targets = [t for t in config.get("targets", []) if t.get("enabled", True)]

    if TEST_NOTIFICATION:
        telegram_send(
            "✅ تست Change Monitor Agent موفق بود.\n"
            f"مدل تنظیم‌شده: {OPENAI_MODEL}"
        )

    if not targets:
        print("No enabled targets.")
        return

    for target in targets:
        name = target.get("name", "Unnamed")
        url = target.get("url")
        if not url:
            print(f"[SKIP] {name}: URL missing")
            continue

        print(f"[FETCH] {name} -> {url}")

        try:
            current_text = fetch_target(url)
        except Exception as exc:
            print(f"[ERROR] Fetch failed for {name}: {exc}")
            continue

        current_hash = sha256(current_text)
        previous = snapshots.get(url)

        if previous is None:
            snapshots[url] = {
                "name": name,
                "hash": current_hash,
                "text": current_text,
            }
            changed_snapshots = True
            print(f"[BASELINE] {name}")
            continue

        if previous.get("hash") == current_hash:
            print(f"[NO CHANGE] {name}")
            continue

        diff = make_diff(previous.get("text", ""), current_text)

        snapshots[url] = {
            "name": name,
            "hash": current_hash,
            "text": current_text,
        }
        changed_snapshots = True

        if not diff.strip():
            print(f"[CHANGE] {name}, but no meaningful text diff.")
            continue

        try:
            result = analyze_change(target, diff)
        except Exception as exc:
            print(f"[ERROR] AI analysis failed for {name}: {exc}")
            continue

        print(
            f"[AI] {name}: relevant={result.get('relevant')} "
            f"score={result.get('score')}"
        )

        threshold = int(target.get("min_score", 6))
        if result.get("relevant") and result.get("score", 0) >= threshold:
            try:
                telegram_send(format_alert(target, result))
                print(f"[ALERT] Telegram sent for {name}")
            except Exception as exc:
                print(f"[ERROR] Telegram failed for {name}: {exc}")

    if changed_snapshots:
        save_json(SNAPSHOTS_FILE, snapshots)
        print("[SAVE] snapshots.json updated")


if __name__ == "__main__":
    run()
