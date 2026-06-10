#!/usr/bin/env python3
"""
notify.py — Intercom SA Tickets notification engine
All notifications → #sales_assisted_tickets

Daily rules (every run):
  1. PRIORITY    — new open priority ticket → @CSM mention
  2. PENDING_SUP — open 48h+, customer sent last msg, no support reply
  3. PENDING_LOW — same as 2, but CX score < 4 (escalated)

Monday only:
  4. WEEKLY DIGEST — priority + feature request tickets, grouped by CSM
"""

import json, os, sys
from datetime import datetime, timezone
from collections import defaultdict
import requests

WEBHOOK = os.environ.get("SLACK_WEBHOOK_SA_TICKETS", "")

INTERCOM_BASE = "https://app.intercom.com/a/inbox/m2ad1co7/inbox/conversation/"
HUB_URL       = "https://harpoon-airslate.github.io/Intercom_SA_tickets_Hub/"
NOTIFIED_FILE = "notified.json"
DATA_FILE     = "data.json"

CSM_SLACK = {
    "Arti Harchekar":                   "U074FAVT1FS",
    "Jayson Lubera":                     "U0442CJ36RG",
    "Dexter Roy Rapsing Hermosura":      "U06CS7Y7VH8",
    "Lynne Pagtalunan":                  "UP8QPAZAN",
    "Marco Francisco Ferrer":            "U01Q6FYK2BC",
    "Russia Vasallo":                    "U01NFS3NNMT",
    "Rachel Kiara Fuellas":              "U01QLKVL1CG",
    "Kurt Daher":                        "U03KFFTNGBA",
    "Federico Mendez":                   "",
}
PRIORITY_CSMS = {"Arti Harchekar", "Jayson Lubera"}


def load_notified():
    try:
        with open(NOTIFIED_FILE) as f:
            return json.load(f)
    except FileNotFoundError:
        return {"priority": [], "pending_support": []}


def save_notified(state):
    with open(NOTIFIED_FILE, "w") as f:
        json.dump(state, f, indent=2)


def post(text):
    if not WEBHOOK:
        print(f"[DRY RUN] {text[:200]}")
        return
    r = requests.post(
        WEBHOOK,
        headers={"Content-Type": "application/json"},
        json={"text": text},
        timeout=10,
    )
    if r.status_code != 200:
        print(f"Slack error: {r.status_code} {r.text}", file=sys.stderr)


def mention(csm):
    uid = CSM_SLACK.get(csm)
    return f"<@{uid}>" if uid else f"*{csm}*"


def turl(t):
    return f"{INTERCOM_BASE}{t.get('intercom_link_id') or t['id']}"


def is_feature_request(t):
    return (t.get("ticket_type") or "").lower() == "feature request"


def main():
    today = datetime.now(timezone.utc)
    is_monday = today.weekday() == 0

    with open(DATA_FILE) as f:
        data = json.load(f)

    tickets  = data.get("tickets", [])
    notified = load_notified()
    changed  = False

    # ── Rule 1: New open priority ticket → @CSM alert ────────────────────────
    for t in tickets:
        if t.get("priority") != "priority" or t.get("state") != "open":
            continue
        tid = str(t["id"])
        if tid in notified["priority"]:
            continue
        csm = t.get("csm", "")
        if csm not in PRIORITY_CSMS:
            continue

        account = t.get("account", "—")
        desc    = t.get("ai_title") or t.get("subject") or "(no description)"
        msg = (
            f":rotating_light: *Priority ticket* — {mention(csm)}\n"
            f"*Account:* {account}\n"
            f"*Topic:* {desc}\n"
            f"<{turl(t)}|Open in Intercom>"
        )
        post(msg)
        notified["priority"].append(tid)
        changed = True
        print(f"[PRIORITY] {csm} | {tid} | {account}")

    # ── Rules 2 & 3: Pending support 48h+ ────────────────────────────────────
    for t in tickets:
        if t.get("state") != "open" or t.get("last_reply_by") != "customer":
            continue
        days = t.get("days_open") or 0
        if days < 2:
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
                f":warning: *Support follow-up — low CX customer*\n"
                f"*Account:* {account}  |  CSM: {csm}\n"
                f"*Ticket:* `{t['id']}` — {days:.0f}d open, customer replied last, no support reply\n"
                f"*CX:* {cx}/5 :red_circle:  <{turl(t)}|Open in Intercom>"
            )
        else:
            msg = (
                f":hourglass_flowing_sand: *Support follow-up needed*\n"
                f"*Account:* {account}  |  CSM: {csm}\n"
                f"*Ticket:* `{t['id']}` — {days:.0f}d open, customer replied last, no support reply\n"
                f"<{turl(t)}|Open in Intercom>"
            )
        post(msg)
        notified["pending_support"].append(tid)
        changed = True
        print(f"[{'PENDING_LOW_CX' if low_cx else 'PENDING_SUP'}] {t['id']} | {account} | {days:.0f}d")

    # ── Rule 4 (Monday only): Weekly digest — priority + feature requests ────
    if is_monday:
        open_tix     = [t for t in tickets if t.get("state") == "open"]
        priority_tix = [t for t in open_tix if t.get("priority") == "priority"]
        fr_tix       = [t for t in tickets if is_feature_request(t)]  # all states

        lines = [
            f":spiral_notepad: *Weekly SA Tickets Digest* — {today.strftime('%b %d, %Y')}  |  <{HUB_URL}|Hub>",
            "",
        ]

        # Priority open — grouped by CSM
        if priority_tix:
            lines.append(f":rotating_light: *Priority open ({len(priority_tix)})*")
            by_csm = defaultdict(list)
            for t in priority_tix:
                by_csm[t.get("csm", "—")].append(t)
            for csm, tix in sorted(by_csm.items()):
                accounts = ", ".join(dict.fromkeys(t.get("account","—")[:40] for t in tix))
                ids      = ", ".join(f"`{t['id']}`" for t in tix)
                lines.append(f"  {mention(csm)}: {accounts} — {ids}")
            lines.append("")

        # Feature requests — grouped by CSM
        if fr_tix:
            lines.append(f":sparkles: *Feature requests ({len(fr_tix)})*")
            by_csm = defaultdict(list)
            for t in fr_tix:
                by_csm[t.get("csm", "—")].append(t)
            for csm, tix in sorted(by_csm.items()):
                accounts = ", ".join(dict.fromkeys(t.get("account","—")[:40] for t in tix))
                ids      = ", ".join(f"`{t['id']}`" for t in tix)
                state_tag = f"({tix[0].get('state','?')})" if len(tix)==1 else ""
                lines.append(f"  {mention(csm)}: {accounts} {state_tag}— {ids}")
            lines.append("")

        if not priority_tix and not fr_tix:
            lines.append(":white_check_mark: No priority or feature request tickets this week.")

        post("\n".join(lines))
        print(f"[WEEKLY DIGEST] Posted — priority:{len(priority_tix)} FR:{len(fr_tix)}")

    if changed:
        save_notified(notified)
        print("notified.json saved.")
    elif not is_monday:
        print("Nothing new to notify.")


if __name__ == "__main__":
    main()
