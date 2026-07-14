#!/usr/bin/env python3
"""
Cloud variant of the Cherry Orchard ticket monitor, run by GitHub Actions.

Checks the RSC API for the three watched performances and emails via Gmail
SMTP when one is no longer sold out. State is kept in state.json (committed
back to the repo by the workflow) so alerts fire on transitions, not every run.

Required env vars (set as GitHub Actions secrets):
  GMAIL_USER, GMAIL_APP_PASSWORD, EMAIL_TO
"""

from __future__ import annotations

import json
import os
import smtplib
import ssl
import sys
import urllib.request
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

API_URL = "https://secure.rsc.org.uk/api/products/productionseasons"
LISTING_URL = (
    "https://secure.rsc.org.uk/events/the-cherry-orchard"
    "?startdate=2026-07-10&enddate=2026-08-29"
)
PRODUCTION_TITLE = "The Cherry Orchard"
TARGET_DATES = {"2026-07-18", "2026-07-20"}
REALERT_TIMES = 3

STATE_FILE = Path(__file__).parent / "state.json"

GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
EMAIL_TO = os.environ["EMAIL_TO"]

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15"
)


def fetch_performances() -> list[dict]:
    payload = json.dumps(
        {"startDate": "2026-07-10T00:00", "endDate": "2026-08-29T23:59"}
    ).encode()
    req = urllib.request.Request(
        API_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
            "Referer": "https://secure.rsc.org.uk/events/the-cherry-orchard",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode())

    matches = []
    for production in data.get("productions", []):
        if production.get("productionTitle") != PRODUCTION_TITLE:
            continue
        for perf in production.get("performances", []):
            if (perf.get("iso8601DateString") or "")[:10] in TARGET_DATES:
                matches.append(perf)
    return matches


def is_available(perf: dict) -> bool:
    status = (perf.get("performanceStatusMessage") or "").strip().lower()
    return bool(perf.get("isOnSale")) or status != "sold out"


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
        state = {"performances": {}}

    performances = fetch_performances()
    if not performances:
        print("WARNING: no matching performances in API response")
        return

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    alerts = []

    for perf in performances:
        pid = str(perf["id"])
        label = f"{perf['displayDate']} {perf['displayTime']}".strip()
        status = (perf.get("performanceStatusMessage") or "").strip() or "On sale"
        available = is_available(perf)
        url = perf.get("actionUrl") or LISTING_URL

        prev = state["performances"].get(pid, {})
        was_available = prev.get("available", False)
        realerts_left = prev.get("realerts_left", 0)

        print(f"[{pid}] {label}: status={status!r} available={available}")

        if available and not was_available:
            alerts.append(f"{label} — now {status!r}!\nBook: {url}")
            realerts_left = REALERT_TIMES
        elif available and realerts_left > 0:
            alerts.append(f"{label} — still available ({status!r}).\nBook: {url}")
            realerts_left -= 1

        state["performances"][pid] = {
            "label": label,
            "available": available,
            "status": status,
            "realerts_left": realerts_left,
            "last_checked": now,
        }

    if alerts:
        send_email(
            "🎭 Cherry Orchard tickets AVAILABLE (cloud check)",
            "The Cherry Orchard is no longer sold out for:\n\n"
            + "\n\n".join(alerts)
            + f"\n\nFull listing: {LISTING_URL}\n\n"
            "(Sent by the GitHub Actions cloud monitor — your Mac may have "
            "already texted you too.)",
        )

    STATE_FILE.write_text(json.dumps(state, indent=2) + "\n")


if __name__ == "__main__":
    main()
