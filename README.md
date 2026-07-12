# Aconex Workflow Auto

Automates Aconex **mail** and **workflow** pulls via official APIs, keeps local SQLite state, exports Excel, and optionally syncs Google Sheets.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# create .env (see below)
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

Optional for Google Sheets schedule:

```bash
GOOGLE_SPREADSHEET_ID=...
GOOGLE_SHEET_PREFIX=WF
```

### First-time OAuth

```bash
python main.py exchange-code --listen --port 8080 --save-env
python main.py token-info
```

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

`google-sheet-update` is the complete scheduled update: it refreshes pending
workflow statuses, scans matching `Final (WF-...)` mail for comments, and
rewrites the managed Google Sheet pages so the comments column is current.

macOS weekday 10:00 schedule:

```bash
zsh scripts/install_google_sheet_schedule.sh
zsh scripts/run_google_sheet_update.sh   # run now
```

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
| `scripts/` | launchd Google Sheet schedule |

## Notes

- Prefer `ACONEX_REFRESH_TOKEN`. On rotation, `.env` is backed up and updated automatically.
- Do not commit `.env`, `google_service_account.json`, or `data/`.
- More detail: [docs/README.md](docs/README.md).
