#!/usr/bin/env python3
"""
notify.py — Intercom SA Tickets notification engine
Runs after fetch_intercom.py in the GitHub Action.

Rules:
  1. PRIORITY    — new open priority ticket → DM to Arti or Jayson
  2. PENDING_SUP — open ticket 48h+ where customer sent last msg → #sn-support
  3. PENDING_LOW — same as 2, but CX score < 4 → escalated message
"""

import json, os, sys
import requests

SLACK_TOKEN        = os.environ.get("SLACK_BOT_TOKEN", "")
INTERCOM_BASE      = "https://app.intercom.com/a/inbox/m2ad1co7/inbox/conversation/"
SN_SUPPORT_CHANNEL = "CA0MB5RNY"
NOTIFIED_FILE      = "notified.json"
DATA_FILE          = "data.json"
PENDING_SUP_HOURS  = 48  # hours before a customer-last ticket triggers a support nudge

# Slack user IDs — update if team changes
CSM_SLACK = {
    "Arti Harchekar":                   "U074FAVT1FS",
    "Jayson Lubera":                     "U0442CJ36RG",
    "Dexter Roy Rapsing Hermosura":      "U06CS7Y7VH8",
    "Lynne Pagtalunan":                  "UP8QPAZAN",
    "Marco Francisco Ferrer":            "U01Q6FYK2BC",
    "Russia Vasallo":                    "U01NFS3NNMT",
    "Rachel Kiara Fuellas":              "U01QLKVL1CG",
    "Kurt Daher":                        "U03KFFTNGBA",
    "Federico Mendez":                   "",  # add Slack UID when known
}

# Only these CSMs have priority accounts — only they receive Rule 1 DMs
PRIORITY_CSMS = {"Arti Harchekar", "Jayson Lubera"}


# ── Helpers ────────────────────────────────────────────────────────────────────

def load_notified():
    """Load previously sent notification IDs to avoid re-firing."""
    try:
        with open(NOTIFIED_FILE) as f:
            return json.load(f)
    except FileNotFoundError:
        return {"priority": [], "pending_support": []}


def save_notified(state):
    with open(NOTIFIED_FILE, "w") as f:
        json.dump(state, f, indent=2)


def post(channel, text):
    """Send a Slack message. Dry-runs if SLACK_BOT_TOKEN is not set."""
    if not SLACK_TOKEN:
        print(f"  [DRY RUN → {channel}] {text[:160]}")
        return {"ok": True, "dry_run": True}
    r = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={
            "Authorization": f"Bearer {SLACK_TOKEN}",
            "Content-Type": "application/json",
        },
        json={"channel": channel, "text": text},
        timeout=10,
    )
    result = r.json()
    if not result.get("ok"):
        print(f"  Slack error [{channel}]: {result.get('error')}", file=sys.stderr)
    return result


def ticket_url(t):
    lid = t.get("intercom_link_id") or t["id"]
    return f"{INTERCOM_BASE}{lid}"


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    with open(DATA_FILE) as f:
        data = json.load(f)

    tickets  = data.get("tickets", [])
    notified = load_notified()
    changed  = False

    # ── Rule 1: New open priority ticket → DM Arti or Jayson ─────────────────
    for t in tickets:
        if t.get("priority") != "priority" or t.get("state") != "open":
            continue

        tid = str(t["id"])
        if tid in notified["priority"]:
            continue

        csm = t.get("csm", "")
        if csm not in PRIORITY_CSMS:
            continue

        uid = CSM_SLACK.get(csm)
        if not uid:
            print(f"  [PRIORITY] No Slack UID for {csm} — skipping ticket {tid}")
            continue

        account = t.get("account", "—")
        desc    = t.get("ai_title") or t.get("subject") or "(no description)"

        msg = (
            f":rotating_light: *Priority ticket opened for one of your accounts*\n"
            f"*Account:* {account}\n"
            f"*Topic:* {desc}\n"
            f"*Intercom:* {ticket_url(t)}"
        )
        post(uid, msg)
        notified["priority"].append(tid)
        changed = True
        print(f"[PRIORITY] DM → {csm} | ticket {tid} | {account}")

    # ── Rules 2 & 3: Pending support 48h+ → #sn-support ─────────────────────
    for t in tickets:
        if t.get("state") != "open":
            continue
        if t.get("last_reply_by") != "customer":
            continue

        days = t.get("days_open") or 0
        if days < 2:      # less than 48 hours
            continue

        tid = str(t["id"])
        if tid in notified["pending_support"]:
            continue

        account = t.get("account", "—")
        csm     = t.get("csm", "—")
        cx      = t.get("cx_score")
        low_cx  = cx is not None and cx < 4

        if low_cx:
            msg = (
                f":warning: *Support follow-up needed — low CX customer*\n"
                f"*Account:* {account}  |  CSM: {csm}\n"
                f"*Ticket:* `{t['id']}` — open *{days:.0f} days*, "
                f"customer replied last, no support response yet\n"
                f"*CX Score:* {cx}/5 :red_circle:\n"
                f"*Intercom:* {ticket_url(t)}"
            )
        else:
            msg = (
                f":hourglass_flowing_sand: *Support follow-up needed*\n"
                f"*Account:* {account}  |  CSM: {csm}\n"
                f"*Ticket:* `{t['id']}` — open *{days:.0f} days*, "
                f"customer replied last, no support response yet\n"
                f"*Intercom:* {ticket_url(t)}"
            )

        post(SN_SUPPORT_CHANNEL, msg)
        notified["pending_support"].append(tid)
        changed = True
        label = "PENDING_LOW_CX" if low_cx else "PENDING_SUPPORT"
        print(f"[{label}] #sn-support | ticket {t['id']} | {account} | {days:.0f}d")

    if changed:
        save_notified(notified)
        print("notified.json saved.")
    else:
        print("Nothing new to notify.")


if __name__ == "__main__":
    main()
