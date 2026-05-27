# Atlas Smiles Weekly Budget Report

Sends a branded HTML budget email to the Atlas Smiles team every Monday and
Thursday at 8am ET. Runs entirely in the cloud via GitHub Actions â no local
machine or browser required.

---

## Repo structure

```
budget_report.py                   # Full implementation
.github/workflows/budget_report.yml  # Cron schedule and job definition
README.md
```

---

## One-time setup

### 1. Add secrets to this repository

Go to **Settings â Secrets and variables â Actions â New repository secret**
and add both of the following:

| Secret name          | Value                                      |
|---------------------|--------------------------------------------|
| `SEQUENCE_API_KEY`   | Your Sequence API key (READ_ACCOUNTS + READ_TRANSFERS) |
| `GMAIL_APP_PASSWORD` | The 16-character App Password from Google  |

### 2. Enable Actions (if not already on)

Go to the **Actions** tab in this repo. If prompted, click
**"I understand my workflows, enable them."**

That's it. The workflow fires automatically on schedule.

---

## Running manually

Go to **Actions â Atlas Smiles Budget Report â Run workflow**.
Useful for testing or sending an on-demand report outside the schedule.

---

## Schedule

Runs at 13:00 UTC every Monday and Thursday:
- **8:00 AM EST** (November â March)
- **9:00 AM EDT** (March â November)

To change the schedule, edit the `cron` value in
`.github/workflows/budget_report.yml`.

---

## If something fails

GitHub will send an email to the repo owner automatically when a workflow run
fails. The Actions tab shows full logs for every run, retained for 90 days.

Common causes:
- `SEQUENCE_API_KEY` expired or revoked â generate a new key in Sequence and update the secret
- `GMAIL_APP_PASSWORD` revoked â generate a new App Password in Google Account settings
- Account name changed in Sequence â update `ACCOUNT_MAP` in `budget_report.py`
