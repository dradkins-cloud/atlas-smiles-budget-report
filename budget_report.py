#!/usr/bin/env python3
"""
Atlas Smiles Weekly Budget Report
----------------------------------
Fetches practice budget balances from the Sequence API and sends a branded
HTML email to the Atlas Smiles team.

Runs automatically via GitHub Actions every Monday and Thursday at 8am ET.
No local machine or browser required.
"""

import os
import ssl
import time
import smtplib
import requests
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# -- Configuration -------------------------------------------------------------

SEQUENCE_API_KEY = os.environ["SEQUENCE_API_KEY"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]

GMAIL_FROM = "dradkins@atlassmilesdental.com"
RECIPIENTS = [
    "didi@atlassmilesdental.com",
    "anais@atlassmilesdental.com",
    "info@atlassmilesdental.com",
    "marketing@atlassmilesdental.com",
]

BASE_URL = "https://api.getsequence.io/platform/v1"
STALE_HOURS = 24  # flag balance if not refreshed within this window

# Sequence account name -> email display name.
# Order here controls row order in the email.
ACCOUNT_MAP = [
    ("Admin / Office Supplies",      "Admin / Office Supplies"),
    ("Lab Fees",                     "Lab Fees"),
    ("Clinical Supplies",            "Clinical Supplies"),
    ("Ortho Supplies",               "Ortho Supplies"),
    ("Jasmine Marketing",            "Internal Marketing"),
    ("Ortho Lab Fees",               "Ortho Lab Fees"),
    ("Anais Smile Patients Now Pod", "Smile Patients Now"),
]

# -- Sequence API --------------------------------------------------------------

def _seq_headers():
    return {
        "Authorization": f"Bearer {SEQUENCE_API_KEY}",
        "x-called-reason": "Atlas Smiles weekly budget report automation",
    }

def _api_get(url, max_retries=2):
    """GET with automatic retry on 429 rate-limit responses."""
    for attempt in range(max_retries + 1):
        resp = requests.get(url, headers=_seq_headers(), timeout=15)
        if resp.status_code == 429:
            if attempt < max_retries:
                wait = int(resp.headers.get("Retry-After", 60))
                print(f"  Rate limited - waiting {wait}s before retry {attempt + 1}...")
                time.sleep(wait)
                continue
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError("Rate limit exceeded after all retries.")

def fetch_pod_accounts():
    """Return all POD accounts from Sequence (up to 100)."""
    data = _api_get(f"{BASE_URL}/accounts?type=POD&pageSize=100")
    return data["data"]["items"]

def fetch_last_transfer_date(account_id):
    """Return the createdAt ISO string of the most recent transfer, or None."""
    try:
        data = _api_get(f"{BASE_URL}/accounts/{account_id}/transfers?pageSize=1")
        items = data["data"]["items"]
        return items[0]["createdAt"] if items else None
    except Exception as exc:
        print(f"  Warning: could not fetch transfers for {account_id}: {exc}")
        return None

def build_account_rows(pod_accounts):
    """
    Match the 7 target accounts by name, fetch supplemental transfer data,
    and return a list of dicts ready for HTML rendering.
    """
    lookup = {a["name"].strip().lower(): a for a in pod_accounts}
    rows = []

    for seq_name, display_name in ACCOUNT_MAP:
        account = lookup.get(seq_name.strip().lower())

        if not account:
            print(f"  Warning: account not found in Sequence - '{seq_name}'")
            rows.append({
                "display_name": display_name,
                "balance_cents": None,
                "last_activity": "N/A",
                "stale": False,
                "found": False,
            })
            continue

        bal = account.get("balance") or {}
        balance_cents = bal.get("availableBalanceInCents")
        last_updated_at = bal.get("balanceLastUpdatedAt")
        last_transfer = fetch_last_transfer_date(account["id"])

        rows.append({
            "display_name": display_name,
            "balance_cents": balance_cents,
            "last_activity": _fmt_date(last_transfer),
            "stale": _is_stale(last_updated_at),
            "found": True,
        })

    return rows

# -- Formatting helpers --------------------------------------------------------

def _fmt_date(iso_str):
    """Parse ISO 8601 UTC timestamp -> 'Mon D' (e.g. 'May 20')."""
    if not iso_str:
        return "N/A"
    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    return f"{dt.strftime('%b')} {dt.day}"

def _fmt_dollars(cents):
    """Convert integer cents -> formatted dollar string (e.g. '$1,204.50')."""
    if cents is None:
        return "N/A"
    amount = abs(cents) / 100
    s = f"${amount:,.2f}"
    return f"-{s}" if cents < 0 else s

def _is_stale(last_updated_at):
    """Return True if the balance timestamp is older than STALE_HOURS."""
    if not last_updated_at:
        return True
    updated = datetime.fromisoformat(last_updated_at.replace("Z", "+00:00"))
    return (datetime.now(timezone.utc) - updated).total_seconds() > STALE_HOURS * 3600

def _monday_of_week():
    """Return 'Month D, YYYY' for the Monday of the current UTC week."""
    today = datetime.now(timezone.utc)
    monday = today - timedelta(days=today.weekday())
    return f"{monday.strftime('%B')} {monday.day}, {monday.year}"

# -- HTML construction ---------------------------------------------------------

def _row_html(row, idx):
    name = row["display_name"]
    found = row["found"]
    cents = row["balance_cents"]
    last_activity = row["last_activity"]
    stale_marker = " *" if row["stale"] else ""
    alt_bg = "#ffffff" if idx % 2 == 0 else "#fafafa"

    # Account not found in Sequence
    if not found:
        return f"""
<tr style="background-color:{alt_bg};">
  <td style="padding:11px 14px;border-bottom:1px solid #eaecef;color:#aaaaaa;font-style:italic;">{name}</td>
  <td style="padding:11px 14px;border-bottom:1px solid #eaecef;text-align:right;color:#aaaaaa;">N/A</td>
  <td style="padding:11px 14px;border-bottom:1px solid #eaecef;text-align:center;color:#aaaaaa;">N/A</td>
  <td style="padding:11px 14px;border-bottom:1px solid #eaecef;text-align:center;">
    <span style="background:#f0f0f0;color:#888888;padding:3px 10px;border-radius:12px;font-size:12px;font-weight:600;">Unavailable</span>
  </td>
</tr>"""

    # Over budget (negative balance)
    if cents is not None and cents < 0:
        return f"""
<tr style="background-color:#fff8f8;">
  <td style="padding:11px 14px;border-bottom:1px solid #f5e0e0;color:#323232;">{name}</td>
  <td style="padding:11px 14px;border-bottom:1px solid #f5e0e0;text-align:right;color:#c0392b;font-weight:700;">{_fmt_dollars(cents)}{stale_marker}</td>
  <td style="padding:11px 14px;border-bottom:1px solid #f5e0e0;text-align:center;color:#555555;">{last_activity}</td>
  <td style="padding:11px 14px;border-bottom:1px solid #f5e0e0;text-align:center;">
    <span style="background:#fde8e8;color:#c0392b;padding:3px 10px;border-radius:12px;font-size:12px;font-weight:600;">Over Budget</span>
  </td>
</tr>"""

    # On track
    return f"""
<tr style="background-color:{alt_bg};">
  <td style="padding:11px 14px;border-bottom:1px solid #eaecef;color:#323232;">{name}</td>
  <td style="padding:11px 14px;border-bottom:1px solid #eaecef;text-align:right;color:#323232;">{_fmt_dollars(cents)}{stale_marker}</td>
  <td style="padding:11px 14px;border-bottom:1px solid #eaecef;text-align:center;color:#555555;">{last_activity}</td>
  <td style="padding:11px 14px;border-bottom:1px solid #eaecef;text-align:center;">
    <span style="background:#e0f5fc;color:#1a7fa0;padding:3px 10px;border-radius:12px;font-size:12px;font-weight:600;">On Track</span>
  </td>
</tr>"""

def _over_budget_banners(rows):
    banners = []
    for row in rows:
        if row["found"] and row["balance_cents"] is not None and row["balance_cents"] < 0:
            overage = _fmt_dollars(abs(row["balance_cents"]))
            banners.append(f"""
<table width="100%" cellpadding="0" cellspacing="0"
  style="background:#fff3cd;border-left:4px solid #e6a817;border-radius:4px;margin-bottom:12px;">
  <tr>
    <td style="padding:12px 16px;font-size:14px;color:#7d5a00;">
      <strong>Over Budget:</strong> <strong>{row['display_name']}</strong>
      is over budget by <strong>{overage}</strong>.
      Please review spending in this category.
    </td>
  </tr>
</table>""")
    return "\n".join(banners)

def _stale_banner(rows):
    stale = [r["display_name"] for r in rows if r["found"] and r["stale"]]
    if not stale:
        return ""
    names = ", ".join(stale)
    return f"""
<table width="100%" cellpadding="0" cellspacing="0"
  style="background:#f0f4ff;border-left:4px solid #6b87d4;border-radius:4px;margin-bottom:16px;">
  <tr>
    <td style="padding:12px 16px;font-size:14px;color:#3a4a7a;">
      * Balance data for <strong>{names}</strong> may not reflect the
      latest transactions &mdash; Sequence had not yet refreshed these accounts
      at report time.
    </td>
  </tr>
</table>"""

def build_html(rows):
    now = datetime.now(timezone.utc)
    day_of_week = now.strftime("%A").upper()
    today_str = f"{now.strftime('%B')} {now.day}, {now.year}"
    rows_html = "\n".join(_row_html(r, i) for i, r in enumerate(rows))
    banners_html = _over_budget_banners(rows)
    stale_html = _stale_banner(rows)

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <link href="https://fonts.googleapis.com/css2?family=Source+Sans+Pro:wght@400;600;700&display=swap" rel="stylesheet">
</head>
<body style="margin:0;padding:0;background-color:#f4f4f4;font-family:'Source Sans Pro',Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background-color:#f4f4f4;padding:24px 0;">
  <tr>
    <td align="center">
      <table width="640" cellpadding="0" cellspacing="0"
        style="background:#ffffff;border-radius:6px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08);">

        <tr>
          <td style="background-color:#323232;padding:24px 32px;text-align:left;">
            <img src="https://atlassmilesdental.com/wp-content/uploads/2022/01/Atlas_Smiles_Logo-1.png"
              alt="Atlas Smiles" height="50" style="display:block;">
          </td>
        </tr>

        <tr><td style="background-color:#30AED6;height:4px;font-size:0;line-height:0;">&nbsp;</td></tr>

        <tr>
          <td style="background-color:#30AED6;padding:14px 32px;">
            <p style="margin:0;color:#ffffff;font-size:16px;font-weight:700;letter-spacing:0.5px;">
              BUDGET UPDATE &nbsp;&middot;&nbsp; {day_of_week}, {today_str.upper()}
            </p>
          </td>
        </tr>

        <tr>
          <td style="padding:28px 32px 8px 32px;">
            <p style="margin:0 0 20px 0;font-size:15px;color:#323232;line-height:1.6;">Good Morning Team!</p>
            <p style="margin:0 0 24px 0;font-size:15px;color:#323232;line-height:1.6;">
              Here is your practice budget snapshot. Review balances and flag any concerns.
            </p>

            {banners_html}
            {stale_html}

            <table width="100%" cellpadding="0" cellspacing="0"
              style="border-collapse:collapse;font-size:14px;margin-bottom:24px;">
              <thead>
                <tr style="background-color:#323232;">
                  <th style="padding:11px 14px;text-align:left;color:#ffffff;font-weight:600;letter-spacing:0.4px;font-size:13px;width:34%;">ACCOUNT</th>
                  <th style="padding:11px 14px;text-align:right;color:#ffffff;font-weight:600;letter-spacing:0.4px;font-size:13px;width:18%;">BALANCE</th>
                  <th style="padding:11px 14px;text-align:center;color:#ffffff;font-weight:600;letter-spacing:0.4px;font-size:13px;width:22%;">LAST ACTIVITY</th>
                  <th style="padding:11px 14px;text-align:center;color:#ffffff;font-weight:600;letter-spacing:0.4px;font-size:13px;width:26%;">STATUS</th>
                </tr>
              </thead>
              <tbody>
                {rows_html}
              </tbody>
            </table>
          </td>
        </tr>

        <tr>
          <td style="padding:20px 32px 28px 32px;border-top:1px solid #eaecef;">
            <p style="margin:0;font-size:12px;color:#888888;line-height:1.6;">
              This report is generated automatically every Monday and Thursday
              morning from your Sequence practice budget.<br>
              <a href="https://www.atlassmilesdental.com"
                style="color:#30AED6;text-decoration:none;">atlassmilesdental.com</a>
            </p>
          </td>
        </tr>

      </table>
    </td>
  </tr>
</table>
</body>
</html>"""

# -- Email send ----------------------------------------------------------------

def send_email(html_body):
    week_of = _monday_of_week()
    subject = f"Atlas Smiles - Budget Update (Week of {week_of})"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = GMAIL_FROM
    msg["To"] = ", ".join(RECIPIENTS)
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
        server.login(GMAIL_FROM, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_FROM, RECIPIENTS, msg.as_string())

    print(f"Sent: '{subject}' -> {', '.join(RECIPIENTS)}")

# -- Entry point ---------------------------------------------------------------

def main():
    print(f"Atlas Smiles budget report - {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")

    print("\nFetching POD accounts from Sequence...")
    pod_accounts = fetch_pod_accounts()
    print(f"  {len(pod_accounts)} POD accounts found.")
    print(f"  Account names returned by API: {sorted([a['name'] for a in pod_accounts])}")

    print("\nMatching target accounts and fetching activity dates...")
    rows = build_account_rows(pod_accounts)

    print("\nAccount summary:")
    for row in rows:
        balance_str = _fmt_dollars(row["balance_cents"]) if row["found"] else "NOT FOUND"
        stale_flag = " [STALE]" if row["stale"] else ""
        print(f"  {row['display_name']:<30} {balance_str:>12}  last activity: {row['last_activity']}{stale_flag}")

    print("\nBuilding HTML and sending email...")
    html = build_html(rows)
    send_email(html)
    print("\nDone.")

if __name__ == "__main__":
    main()
