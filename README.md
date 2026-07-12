# Aconex Workflow Auto

Automates Aconex **mail** and **workflow** pulls via official APIs, keeps local SQLite state, exports Excel, and optionally syncs Google Sheets and DocFlow.

Designed to run unattended on an **Ubuntu VPS** (cron, weekdays 10:00).

## Setup (Ubuntu VPS)

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip

git clone <your-repo-url> Acoenx
cd Acoenx

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# create .env (see below)
# place google_service_account.json in the project root
python main.py init-db
```

### `.env` (required)

```bash
ACONEX_AUTHORIZATION_URL=https://constructionandengineering.oraclecloud.com/auth/authorize
ACONEX_TOKEN_URL=https://constructionandengineering.oraclecloud.com/auth/token
ACONEX_BASE_URL=https://eu1.aconex.com
ACONEX_API_AUDIENCE=https://api.aconex.com
ACONEX_CLIENT_ID=...
ACONEX_CLIENT_SECRET=...
ACONEX_REDIRECT_URI=http://localhost:8080/callback
ACONEX_REFRESH_TOKEN=...          # preferred; auto-rotated into .env
ACONEX_PROJECT_ID=...
ACONEX_DEFAULT_MAIL_BOX=inbox
ACONEX_PAGE_SIZE=250
DOCFLOW_BASE_URL=https://feizhang233.com
DOCFLOW_API_KEY=...                # same value as the web server EXTERNAL_API_KEY
CF_ACCESS_CLIENT_ID=...            # Cloudflare Access Service Token client ID
CF_ACCESS_CLIENT_SECRET=...        # Cloudflare Access Service Token client secret
```

Required for the scheduled Google Sheets update:

```bash
GOOGLE_SPREADSHEET_ID=...
GOOGLE_SHEET_PREFIX=WF
```

### First-time OAuth

Run once (locally or on the VPS with port access):

```bash
python main.py exchange-code --listen --port 8080 --save-env
python main.py token-info
```

After a valid `ACONEX_REFRESH_TOKEN` is in `.env`, unattended runs no longer need a browser.

## Everyday commands

### Workflow → SQLite + Excel

```bash
python main.py workflow-db-sync-all
python main.py workflow-db-sync-changed
python main.py docflow-workflow-push-all
python main.py docflow-workflow-push-changed
python main.py export-workflow-status --from-number 800
```

The DocFlow commands read only the local SQLite database; they never contact
Aconex. `workflow-db-sync-all` imports all Aconex workflows. For regular
updates, use `workflow-db-sync-changed`, which refreshes current workflows and
locally pending workflows. `docflow-workflow-push-changed` publishes only
workflow payloads not yet handled by DocFlow; a `404 Workflow not found` is a
normal skipped result and is not retried unless the workflow status changes.
All DocFlow requests include the Cloudflare Access Service Token headers when
`CF_ACCESS_CLIENT_ID` and `CF_ACCESS_CLIENT_SECRET` are configured.

### Mail → Final workflow comments

```bash
python main.py mail-scan-final-all
python main.py mail-scan-final-from --from-number 800
python main.py mail-scan-final-recent --hours 48 --from-number 800
```

### Google Sheets

Put service account JSON at `google_service_account.json` and share the sheet with that email.

```bash
python main.py google-sheet-sync-all --spreadsheet-id YOUR_ID
python main.py google-sheet-sync-reviewing --spreadsheet-id YOUR_ID
python main.py google-sheet-update --spreadsheet-id YOUR_ID
```

`google-sheet-update` refreshes pending workflow statuses, scans matching
`Final (WF-...)` mail for comments, writes them to SQLite, and rewrites the
managed Google Sheet pages so the comments column is current.

## Daily weekday pipeline (VPS)

`daily-update` is the end-to-end job for unattended runs:

1. Pull changed Aconex workflows and matching Final-mail comments into SQLite
2. Update Google Sheets from the database
3. Push changed workflow statuses from the database to DocFlow

### Run once manually

```bash
bash scripts/run_daily_update.sh
# or:
source .venv/bin/activate
python main.py daily-update --spreadsheet-id YOUR_ID
```

### Install cron (Mon–Fri 10:00, server local time)

```bash
# set timezone to Belgrade (CET/CEST) so weekday 10:00 is local there
sudo timedatectl set-timezone Europe/Belgrade

bash scripts/install_daily_update_cron.sh
```

This installs a user crontab entry:

```cron
0 10 * * 1-5 /path/to/Acoenx/scripts/run_daily_update.sh >>.../logs/daily_update.log 2>>.../logs/daily_update.error.log
```

Useful checks:

```bash
crontab -l                          # list jobs
bash scripts/run_daily_update.sh    # run now
tail -f logs/daily_update.log       # follow success log
tail -f logs/daily_update.error.log # follow errors
timedatectl                         # confirm timezone
```

Remove the job:

```bash
crontab -l | grep -vF '# aconex-daily-update' | crontab -
```

Requires `GOOGLE_SPREADSHEET_ID` plus DocFlow / Cloudflare Access keys in `.env`.

### Low-level fetch / offline normalize

```bash
python main.py fetch-mail-list
python main.py fetch-mail-detail --mail-id 123456
python main.py fetch-workflow-list
python main.py normalize-mail
python main.py normalize-workflow
```

Raw responses → `data/raw/`; Excel → `data/output/`; DB → `data/state/aconex.sqlite`.

## Layout

| Path | Purpose |
| --- | --- |
| `main.py` | CLI entry |
| `aconex/` | Auth, API client, sync, exports |
| `postprocess/` | Offline normalize (no API calls) |
| `data/` | Generated raw/parsed/output/state (gitignored) |
| `docs/api/` | Mail & Workflow API PDFs |
| `scripts/run_daily_update.sh` | Daily pipeline runner |
| `scripts/install_daily_update_cron.sh` | Install weekday 10:00 cron on Ubuntu |

## Notes

- Prefer `ACONEX_REFRESH_TOKEN`. On rotation, `.env` is backed up and updated automatically.
- Cron uses the **server local timezone**. Use `Europe/Belgrade` so weekday 10:00 is Belgrade time.
- Keep the VPS user session able to write `.env` (token rotation) and `data/state/`.
- Do not commit `.env`, `google_service_account.json`, or `data/`.
- More detail: [docs/README.md](docs/README.md).
