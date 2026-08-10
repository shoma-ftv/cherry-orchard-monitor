#!/usr/bin/env python3
"""
Cloud ticket monitor, run by GitHub Actions.

Watches the Salzburg Festival "Vienna Philhamonic · Muti" concert
(Sat 15 Aug 2026, 11:00, Grosses Festspielhaus) and emails via Gmail
SMTP when the buy button goes live. State is kept in state.json
(committed back by the workflow) so alerts fire on transitions.

Required env vars (set as GitHub Actions secrets):
  GMAIL_USER, GMAIL_APP_PASSWORD, EMAIL_TO
"""

from __future__ import annotations

import json
import os
import smtplib
import ssl
import urllib.request
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

JT_ID = 8665
API_URL = f"https://www.salzburgerfestspiele.at/vue/availability/en/event/{JT_ID}"
EVENT_URL = "https://www.salzburgerfestspiele.at/en/p/vienna-philhamonic-muti-2026#tickets"
EVENT_LABEL = "Vienna Philharmonic · Muti — Sat 15 Aug 2026, 11:00"

NOT_BUYABLE = {"UNAVAILABLE", "SOLD-OUT", "SOLDOUT", "CANCELLED"}
CATEGORY_PRICES = {
    "1": "€260", "2": "€225", "3": "€180", "4": "€150", "5": "€120",
    "6": "€90", "7": "€50", "8": "€20", "9": "€30 (wheelchair)",
}
REALERT_TIMES = 3

STATE_FILE = Path(__file__).parent / "state.json"

GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
EMAIL_TO = os.environ["EMAIL_TO"]

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15"
)


def fetch_availability() -> dict:
    req = urllib.request.Request(
        API_URL,
        headers={
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
            "Referer": EVENT_URL,
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def describe_seats(availabilities: dict) -> str:
    parts = [
        f"{n}x at {CATEGORY_PRICES.get(str(cat), f'category {cat}')}"
        for cat, n in sorted(availabilities.items(), key=lambda kv: str(kv[0]))
        if n
    ]
    return ", ".join(parts) if parts else "no per-category counts shown"


def send_email(subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = GMAIL_USER
    msg["To"] = EMAIL_TO
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465,
                          context=ssl.create_default_context()) as s:
        s.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        s.send_message(msg)
    print(f"Email sent to {EMAIL_TO}: {subject}")


def main() -> None:
    try:
        state = json.loads(STATE_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        state = {}
    if "buyable" not in state:  # reset leftover Cherry Orchard state shape
        state = {"buyable": False, "realerts_left": 0}

    data = fetch_availability()
    button_type = ((data.get("button") or {}).get("type") or "").strip().upper()
    availabilities = data.get("availabilities") or {}
    total = sum(v for v in availabilities.values() if isinstance(v, (int, float)))
    buyable = bool(button_type) and button_type not in NOT_BUYABLE

    print(f"button={button_type!r} total_seats={total} avail={availabilities}")

    was_buyable = state.get("buyable", False)
    realerts_left = state.get("realerts_left", 0)

    if buyable and not was_buyable:
        send_email(
            "🎻 Salzburg TICKETS AVAILABLE — VPO/Muti Aug 15 (cloud check)",
            f"{EVENT_LABEL}: the buy button is live ({button_type}).\n"
            f"Seats: {describe_seats(availabilities)}\n\n"
            f"Book: {EVENT_URL}\n\n"
            "(Sent by the GitHub Actions cloud monitor — your Mac may have "
            "already texted you too.)",
        )
        realerts_left = REALERT_TIMES
    elif buyable and realerts_left > 0:
        send_email(
            "🎻 Reminder: VPO/Muti Aug 15 still available (cloud check)",
            f"{EVENT_LABEL}: {describe_seats(availabilities)}\n\nBook: {EVENT_URL}",
        )
        realerts_left -= 1

    state = {
        "buyable": buyable,
        "button_type": button_type,
        "availabilities": availabilities,
        "realerts_left": realerts_left,
        "last_checked": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    STATE_FILE.write_text(json.dumps(state, indent=2) + "\n")


if __name__ == "__main__":
    main()
