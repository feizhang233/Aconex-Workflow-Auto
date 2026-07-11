from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import requests

from .client import AconexClient
from .config import Settings
from .export_workflow_status import fetch_workflow_status_rows
from .state_db import (
    add_update_run,
    add_workflow_history,
    load_workflows,
    upsert_workflow,
)
from .workflow_sync import (
    _change_summary,
    _db_row,
    _history_payload,
    _status_changed,
)


@dataclass(frozen=True)
class WebWorkflowSyncResult:
    checked: int
    changed: int
    sent: int
    skipped: int
    failed: int


def sync_web_workflows(
    settings: Settings,
    client: AconexClient,
    *,
    changed_only: bool,
    base_url: str | None = None,
    api_key: str | None = None,
    max_pages: int | None = None,
    save_raw: bool = False,
) -> WebWorkflowSyncResult:
    """Fetch every Aconex workflow and publish its review state to DocFlow.

    Incremental mode still scans Aconex completely so transitions from open to
    completed/terminated cannot be missed; it only sends rows whose tracked
    status differs from the local SQLite snapshot.
    """
    url = (base_url or settings.docflow_base_url).rstrip("/")
    key = api_key or settings.docflow_api_key
    if not url:
        raise ValueError("DOCFLOW_BASE_URL or --web-base-url is required")
    if not key:
        raise ValueError("DOCFLOW_API_KEY or --api-key is required")

    rows = fetch_workflow_status_rows(
        settings,
        client,
        from_number=None,
        max_pages=max_pages,
        save_raw=save_raw,
    )
    old_by_id = {
        str(row["workflow_id"]): row
        for row in load_workflows()
        if row.get("workflow_id")
    }
    reviewers = _load_feedback_reviewers(url)
    checked_at = _utc_now()
    changed = sent = skipped = failed = 0

    with requests.Session() as session:
        session.headers.update({"X-API-Key": key, "Accept": "application/json"})
        for raw_row in rows:
            workflow_number = str(raw_row.get("workflow_number") or "").strip()
            try:
                row = _db_row(raw_row, checked_at=checked_at, source="web-workflow-sync")
                old_row = old_by_id.get(row["workflow_id"])
                row_changed = _status_changed(old_row, row)
                if row_changed:
                    changed += 1
                    add_workflow_history(
                        row["workflow_id"],
                        workflow_number=row["workflow_number"],
                        checked_at=checked_at,
                        change_summary=_change_summary(old_row, row),
                        old_data_json=_history_payload(old_row) if old_row else None,
                        new_data_json=_history_payload(row),
                    )

                if not changed_only or row_changed:
                    response = session.patch(
                        _workflow_url(url, workflow_number),
                        json=_web_payload(row, reviewers),
                        timeout=30,
                    )
                    if response.status_code == 404:
                        skipped += 1
                        print(f"Skipped workflow not present in DocFlow: {workflow_number}")
                    else:
                        response.raise_for_status()
                        sent += 1

                upsert_workflow(row)
            except Exception as exc:
                failed += 1
                print(f"Failed to publish workflow {workflow_number or '<unknown>'}: {exc}")

    command = "web-workflow-sync-changed" if changed_only else "web-workflow-sync-all"
    result = WebWorkflowSyncResult(
        checked=len(rows), changed=changed, sent=sent, skipped=skipped, failed=failed
    )
    add_update_run(
        command=command,
        run_time=checked_at,
        checked_count=result.checked,
        changed_count=result.changed,
        failed_count=result.failed,
        notes=f"sent={result.sent}, skipped={result.skipped}",
    )
    return result


def _load_feedback_reviewers(base_url: str) -> tuple[str, str]:
    response = requests.get(f"{_api_root(base_url)}/settings/workflow", timeout=30)
    response.raise_for_status()
    reviewers = response.json().get("feedback_reviewers") or []
    if len(reviewers) != 2 or not all(str(value).strip() for value in reviewers):
        raise ValueError("DocFlow workflow settings must contain exactly two feedback reviewers")
    return str(reviewers[0]), str(reviewers[1])


def _web_payload(row: Mapping[str, Any], reviewers: tuple[str, str]) -> dict[str, Any]:
    step_1 = _feedback_code(row.get("step_1_review_status"))
    step_2 = _feedback_code(row.get("step_2_review_status"))
    terminated = str(row.get("review_status") or "").strip().casefold() == "terminate"
    return {
        "feedback_status": {reviewers[0]: step_1, reviewers[1]: step_2},
        "feedback": {
            reviewers[0]: step_1 != "P",
            reviewers[1]: step_2 != "P",
            "Terminate": terminated,
        },
        "terminate_workflow": terminated,
        "message": "Aconex workflow status synchronized.",
    }


def _feedback_code(value: Any) -> str:
    normalized = str(value or "").strip().upper()
    if normalized.startswith(("A-", "A ")) or normalized == "A":
        return "A"
    if normalized.startswith(("B-", "B ")) or normalized == "B":
        return "B"
    if normalized.startswith(("C-", "C ")) or normalized == "C":
        return "C"
    return "P"


def _api_root(base_url: str) -> str:
    value = base_url.rstrip("/")
    return value if value.endswith("/api") else f"{value}/api"


def _workflow_url(base_url: str, workflow_number: str) -> str:
    return f"{_api_root(base_url)}/external/workflows/{quote(workflow_number, safe='')}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
