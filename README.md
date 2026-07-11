# Aconex Data Automation

This project is a clean rebuild of the Aconex data automation workflow.

Phase 1 fetches and saves raw API responses plus field inventories. Phase 2 is only scaffolded: it reads saved raw/parsed files and does not call Aconex APIs.

## Project Layout

- `aconex/` — API client, authentication, fetching, synchronization, and exports.
- `postprocess/` — transforms saved raw responses into normalized workbooks.
- `data/` — generated API captures, parsed inventories, Excel outputs, and local state.
- `docs/` — stable reference material; see [the documentation index](docs/README.md).
- `main.py` — command-line entry point.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configure `.env`

Fill these values in `.env`:

```bash
ACONEX_AUTHORIZATION_URL=https://constructionandengineering.oraclecloud.com/auth/authorize
ACONEX_TOKEN_URL=https://constructionandengineering.oraclecloud.com/auth/token
ACONEX_BASE_URL=https://eu1.aconex.com
ACONEX_API_AUDIENCE=https://api.aconex.com
ACONEX_CLIENT_ID=SCP_NFS_Aconex_ACONEX_client_APPID
ACONEX_CLIENT_SECRET=
ACONEX_TOKEN_AUTH_METHOD=basic
ACONEX_REDIRECT_URI=http://localhost:8080/callback
ACONEX_STATE=aconex-local-auth
ACONEX_AUTHORIZATION_CODE=
ACONEX_REFRESH_TOKEN=
ACONEX_ACCESS_TOKEN=
ACONEX_PROJECT_ID=671090433
ACONEX_DEFAULT_MAIL_BOX=inbox
ACONEX_PAGE_SIZE=250
```

Recommended token source is `ACONEX_REFRESH_TOKEN`. `ACONEX_ACCESS_TOKEN` is only a temporary debug fallback and will expire.

`ACONEX_TOKEN_AUTH_METHOD` defaults to `basic`, which sends `ACONEX_CLIENT_ID` and `ACONEX_CLIENT_SECRET` using HTTP Basic Auth at the token endpoint. Set it to `form` only if your Oracle app explicitly expects client credentials in the request body.

Aconex may rotate refresh tokens. When any command uses `ACONEX_REFRESH_TOKEN` and the token endpoint returns a new refresh token, the script automatically creates a `.env.bak.YYYYMMDDTHHMMSS` backup, updates `ACONEX_REFRESH_TOKEN`, and clears `ACONEX_AUTHORIZATION_CODE` and `ACONEX_ACCESS_TOKEN`. It prints only `refresh_token_rotated` and `.env updated`, never the full refresh token.

This project does not use OAuth1 values, browser cookies, `JSESSIONID`, `ASESSIONID`, `XSRF-TOKEN`, Web Sessions, or `/SearchWorkFlow`.

## Local State Database

Initialize the SQLite state database:

```bash
python main.py init-db
```

This creates `data/state/aconex.sqlite`. The local database is the long-term sync state store; Excel files remain final outputs only.

## Token Commands

Print the OAuth authorization URL only:

```bash
python main.py print-auth-url
```

Inspect non-sensitive token metadata:

```bash
python main.py token-info
```

`token-info` also tests refresh-token validity. If no refresh token is configured, it prints:

```bash
Run: python main.py exchange-code --listen --port 8080 --save-env
```

Exchange an authorization code for tokens:

```bash
python main.py exchange-code
```

Run the local callback listener flow:

```bash
python main.py exchange-code --listen --port 8080 --save-env
```

This prints the authorization URL, listens on `127.0.0.1:8080/callback`, reads the returned `code`, exchanges it for tokens, creates a `.env.bak.YYYYMMDDTHHMMSS` backup, writes `ACONEX_REFRESH_TOKEN`, and clears `ACONEX_AUTHORIZATION_CODE` and `ACONEX_ACCESS_TOKEN`.

If you omit `--save-env`, the command keeps the safer manual mode: it does not modify `.env` and only reminds you to save the returned refresh token.

Without `--listen`, `exchange-code` keeps the original behavior and reads `ACONEX_AUTHORIZATION_CODE` from `.env`.

## Project Test

```bash
python main.py fetch-projects
```

This CLI entry is intentionally present but not implemented because the uploaded Mail and Workflow API guides do not define a project-list endpoint. The configured project id is used directly by the Mail and Workflow commands.

## Mail Fetching

Implemented from the uploaded Mail API guide:

- List Mail: `GET /api/projects/{projectid}/mail?{parameters}`
- View Mail Metadata: `GET /api/projects/{projectid}/mail/{mailId}`
- Download Mail Attachment: `GET /api/projects/{projectid}/mail/{mailid}/attachments/{attachmentid}/[markedup]`

Fetch mail list with official paged search parameters:

```bash
python main.py fetch-mail-list
python main.py fetch-mail-list --mail-box inbox --page-size 250 --max-pages 2
python main.py fetch-mail-list --search-query 'tostatusid:2'
```

Fetch a single mail metadata response:

```bash
python main.py fetch-mail-detail --mail-id 123456
```

Fetch details for IDs found in the first saved list page:

```bash
python main.py fetch-mail-details --limit 20
```

Fetch downloadable attachment files whose `attachmentId` values appear in the mail metadata response:

```bash
python main.py fetch-mail-attachments --mail-id 123456
python main.py fetch-mail-attachments --mail-id 123456 --markedup
```

All raw Mail API responses are saved under `data/raw/mail/`. Field inventories are saved under `data/parsed/mail/`.

## Workflow Fetching

Implemented from the uploaded Workflow API guide:

- Search workflows of project: `GET /api/projects/{project_id}/workflows?{parameters}`
- Search initiated by user's organization: `GET /api/projects/{project_id}/workflows/initiated-by/us?{parameters}`
- Search not initiated by user's organization: `GET /api/projects/{project_id}/workflows/initiated-by/others?{parameters}`
- Search assigned to user's organization: `GET /api/projects/{project_id}/workflows/assigned-to/us?{parameters}`
- Search not assigned to user's organization: `GET /api/projects/{project_id}/workflows/assigned-to/others?{parameters}`
- Search by workflow numbers: `GET /api/projects/{project_id}/workflows/search?workflow_number=...`
- Status variants such as `GET /api/projects/{project_id}/workflows/current?{parameters}` and official initiated/assigned status paths.

Fetch workflow list:

```bash
python main.py fetch-workflow-list
python main.py fetch-workflow-list --page-size 250 --max-pages 2
python main.py fetch-workflow-list --updated-after 2026-01-01T00:00:00Z
python main.py fetch-workflow-list --search-mode assigned-to-us --status current
python main.py fetch-workflow-list --search-mode search-by-number --workflow-number WF-000020,WF-000021
```

The uploaded Workflow API guide does not define a separate `GET /workflows/{workflow_id}` detail endpoint. Therefore these commands are intentionally guarded and will not guess an endpoint:

```bash
python main.py fetch-workflow-detail --workflow-id xxx
python main.py fetch-workflow-details --limit 20
```

Use `fetch-workflow-list` or `fetch-workflow-list --search-mode search-by-number` as the official raw workflow detail source for now.

All raw Workflow API responses are saved under `data/raw/workflow/`. Field inventories are saved under `data/parsed/workflow/`.

Quick export workflow status after workflow number 800:

```bash
python main.py export-workflow-status --from-number 800
```

Output:

```text
data/output/workflow_status_after_800.xlsx
```

This command calls the official Workflow API directly, parses XML in memory, and writes a single-sheet Excel workbook named `Workflow Status`. It does not generate field inventories, `workflow_normalized.xlsx`, or raw XML by default.

To limit API paging during testing:

```bash
python main.py export-workflow-status --from-number 800 --max-pages 5
```

For this quick export, the command first locates the first page likely to contain `--from-number`, then applies `--max-pages` from that page onward. This avoids scanning only the oldest workflow pages when you ask for high workflow numbers such as 800.

To write a custom output path:

```bash
python main.py export-workflow-status --from-number 800 --output data/output/custom.xlsx
```

If you need to debug original XML responses:

```bash
python main.py export-workflow-status --from-number 800 --save-raw
```

## Workflow State Sync

Synchronize all workflows into SQLite and write the full Excel output:

```bash
python main.py workflow-sync-all
```

Synchronize workflow status from workflow number 800 onward:

```bash
python main.py workflow-sync-from --from-number 800
```

Update only workflows currently marked open in `data/state/aconex.sqlite`:

```bash
python main.py workflow-update-open
```

Incrementally sync only new and reviewing workflows:

```bash
python main.py workflow-sync-reviewing
```

This command discovers currently reviewing workflows through the official
`/workflows/current` endpoint, inserts any that are not yet in SQLite, and refreshes
only rows already marked open. Completed records already stored in SQLite are skipped.

## Google Sheets Sync

Place the service-account JSON at `google_service_account.json` (already supported by
default) and share the target Google Sheet with the service account email as an editor.
The target sheet has these columns: Workflow Number, Workflow Title, both step due
times, both step review statuses, both overdue values, and Workflow Comments.

Fetch every workflow from Aconex, then replace the target tabs:

```bash
python main.py google-sheet-sync-all --spreadsheet-id YOUR_SPREADSHEET_ID
```

Query pending (not-yet-completed) Workflows from the local SQLite database, refresh
them through Aconex, and also query Aconex's current-pending endpoint to discover new
Workflows. It then updates only the changed or newly added Workflow rows in the
existing Google Sheets tabs. If the workflow tabs do not yet exist, it initializes
them from the current local Workflow state:

```bash
python main.py google-sheet-sync-reviewing --spreadsheet-id YOUR_SPREADSHEET_ID
```

Both commands write no more than 200 Workflows per tab. Tabs are named
`WF0001-0200`, `WF0201-0400`, and so on. The Reviewing sync also creates a
`WF Refresh Log` tab and appends the refresh timestamp plus the count of refreshed,
changed, and newly added Workflows. It also logs the count and comma-separated
Workflow numbers for Step 1 → Step 2 transitions and Step 2 completions; titles are
not included. A subsequent sync removes surplus numbered tabs created by this
exporter. Add `--sheet-name "Your Prefix"` to change the `WF` prefix, and use
`--credentials-file /path/to/service-account.json` to override the default JSON path.

This routine does not re-fetch completed historical Workflows. Use
`google-sheet-sync-all` for a full historical reconciliation.

### Weekday 10:00 Scheduled Update (macOS)

Add the target workbook ID to `.env`:

```bash
GOOGLE_SPREADSHEET_ID=YOUR_SPREADSHEET_ID
GOOGLE_SHEET_PREFIX=WF
```

Install the local `launchd` schedule once. It runs the Pending Workflow update at
10:00 on Monday through Friday in the Mac's local time zone:

```bash
zsh scripts/install_google_sheet_schedule.sh
```

The update output and errors are saved to `logs/google_sheet_update.log` and
`logs/google_sheet_update.error.log`. To run the same update immediately, use:

```bash
zsh scripts/run_google_sheet_update.sh
```

These commands use the official Workflow API, the existing OAuth refresh token rotation, and the local SQLite state database. They do not use `/SearchWorkFlow`, cookies, or raw XML saving by default. Add `--save-raw` when raw API responses are needed for debugging. All three commands support `--max-pages` and `--output`; `workflow-sync-from` also supports `--from-number`.

## Mail Final Workflow Scan

Scan all Mail for Final workflow comments:

```bash
python main.py mail-scan-final-all
```

Scan Mail for Final workflow comments from workflow number 800 onward:

```bash
python main.py mail-scan-final-from --from-number 800
```

Scan recent Mail, defaulting to the last 48 hours and workflow number 800 onward:

```bash
python main.py mail-scan-final-recent --hours 48 --from-number 800
```

These commands use the official Mail API and the existing OAuth refresh token rotation. Final Workflow mail is matched from subjects such as `Final (WF-000800)`. Comments are extracted first from `MESSAGE` / body HTML by parsing the Workflow Review History table and using the `Comments` column together with Step, Participant, and Review Outcome. If that table cannot be parsed, the scanner falls back to ordinary comments/body/message/remarks/response fields. Workflow references are normalized to `WF-000800`, then written to `workflow_comments`, `update_runs`, and final Excel files under `data/output/`. Raw Mail XML is not saved unless `--save-raw` is provided. Add `--debug-candidates` to print each matched mail id, subject, workflow number, review-row count, and extracted comment preview.

## Post-processing

Post-processing reads only `data/raw` and `data/parsed`; it does not call Aconex APIs.

```bash
python main.py normalize-mail
python main.py normalize-workflow
```

These commands create the focused Mail comments and Workflow workbooks under `data/output/`.

`normalize-mail` is intentionally limited to saved Mail detail XML for subjects in the form
`Final (WF-001038) title`. It extracts only the `Comments` values from the
`Workflow Review History` table in the mail body and writes one `Workflow Comments`
sheet with `workflow_no` and `comments`. Each workflow has one row; distinct comments
are separated by line breaks and identical whitespace-normalized comments are written
once. Mail list XML does not contain the message
body, so run a detail fetch (or a Final mail scan with `--save-raw`) before using this
offline command.

## Raw Response Policy

Every API response is saved, including failures. Each response has:

- raw body file under `data/raw/...`
- `.meta.json` sidecar with method, URL, status code, content type, headers, preview, and body path

Sensitive values such as bearer tokens, refresh tokens, client secrets, and cookies are not written to logs or metadata by this code.
