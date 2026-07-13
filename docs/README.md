# Documentation Index

This directory contains stable project reference material. Generated data and
runtime state remain under `data/` and are intentionally kept out of version
control.

## API References

- [Mail API](api/mail-api.pdf) — Aconex Mail endpoints and response formats.
- [Workflow API](api/workflow-api.pdf) — Aconex Workflow endpoints and response formats.

## Project Data Map

| Location | Contents | Handling |
| --- | --- | --- |
| `data/raw/mail/` | Original Mail API XML and metadata | Generated; keep for traceability |
| `data/raw/workflow/` | Original Workflow API XML and metadata | Generated; keep for traceability |
| `data/parsed/mail/` | Mail field-inventory CSV files | Generated |
| `data/parsed/workflow/` | Workflow field-inventory CSV files | Generated |
| `data/output/` | Excel deliverables | Generated; share/export as needed |
| `data/state/` | Local SQLite sync database, backup, and weekly update manifest | Runtime state; do not commit |

## Sensitive Local Files

- `.env` and its `.env.bak.*` backups contain authentication configuration.
- `google_service_account.json` is used by the optional Google Sheets export and
  stays in the project root because that is the CLI default path.

These files are excluded through `.gitignore` and should not be shared.
