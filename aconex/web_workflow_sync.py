from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
from typing import Any
from urllib.parse import quote

import requests

from .config import Settings
from .state_db import (
    add_update_run,
    load_docflow_sync_state,
    load_workflows,
    upsert_docflow_sync_state,
)
from .workflow_update_manifest import mark_manifest_sync, pending_manifest_workflows


@dataclass(frozen=True)
class DocFlowPushResult:
    checked: int
    sent: int
    skipped: int
    failed: int


def push_workflows_to_docflow(
    settings: Settings,
    *,
    changed_only: bool,
    base_url: str | None = None,
    api_key: str | None = None,
) -> DocFlowPushResult:
    """Push locally stored workflow states to DocFlow without contacting Aconex."""
    pending = pending_manifest_workflows("docflow")
    pending_ids = {str(entry["workflow_id"]) for entry in pending}
    if changed_only and not pending:
        result = DocFlowPushResult(checked=0, sent=0, skipped=0, failed=0)
        add_update_run(
            command="docflow-workflow-push-changed",
            notes="sent=0, skipped=0; manifest queue empty",
        )
        return result

    url = (base_url or settings.docflow_base_url).rstrip("/")
    key = api_key or settings.docflow_api_key
    if not url:
        raise ValueError("DOCFLOW_BASE_URL or --web-base-url is required")
    if not key:
        raise ValueError("DOCFLOW_API_KEY or --api-key is required")

    workflows = load_workflows()
    missing_ids: set[str] = set()
    if changed_only:
        workflows = [
            row for row in workflows if str(row.get("workflow_id") or "") in pending_ids
        ]
        found_ids = {str(row.get("workflow_id") or "") for row in workflows}
        missing_ids = pending_ids - found_ids
        if missing_ids:
            mark_manifest_sync(
                "docflow",
                missing_ids,
                success=False,
                error="Workflow is missing from SQLite",
            )
    headers = _docflow_headers(settings, key)
    try:
        reviewers = _gds_as_step_2(_load_feedback_reviewers(url, headers=headers))
    except Exception as exc:
        if pending_ids:
            mark_manifest_sync(
                "docflow",
                (entry["workflow_id"] for entry in pending),
                success=False,
                error=str(exc),
            )
        raise
    prior_hashes = load_docflow_sync_state() if changed_only else {}
    sent = skipped = failed = 0

    with requests.Session() as session:
        session.headers.update(headers)
        for row in workflows:
            workflow_id = str(row.get("workflow_id") or "").strip()
            workflow_number = str(row.get("workflow_number") or "").strip()
            if not workflow_id or not workflow_number:
                failed += 1
                print(f"Failed to publish workflow {workflow_number or '<unknown>'}: missing workflow ID or number")
                if workflow_id in pending_ids:
                    mark_manifest_sync(
                        "docflow",
                        [workflow_id],
                        success=False,
                        error="Missing workflow ID or number",
                    )
                continue

            payload = _web_payload(row, reviewers)
            payload_hash = _payload_hash(payload)
            if changed_only and prior_hashes.get(workflow_id) == payload_hash:
                mark_manifest_sync("docflow", [workflow_id], success=True)
                continue

            try:
                response = session.patch(
                    _workflow_url(url, workflow_number), json=payload, timeout=30
                )
                if response.status_code == 404:
                    skipped += 1
                    print(f"Skipped workflow not present in DocFlow: {workflow_number}")
                else:
                    response.raise_for_status()
                    sent += 1
                # A missing DocFlow workflow is intentionally considered handled.
                upsert_docflow_sync_state(workflow_id, payload_hash)
                if workflow_id in pending_ids:
                    mark_manifest_sync("docflow", [workflow_id], success=True)
            except requests.RequestException as exc:
                failed += 1
                print(f"Failed to publish workflow {workflow_number}: {exc}")
                if workflow_id in pending_ids:
                    mark_manifest_sync(
                        "docflow", [workflow_id], success=False, error=str(exc)
                    )

    command = "docflow-workflow-push-changed" if changed_only else "docflow-workflow-push-all"
    result = DocFlowPushResult(
        checked=len(pending) if changed_only else len(workflows),
        sent=sent,
        skipped=skipped,
        failed=failed + (len(missing_ids) if changed_only else 0),
    )
    add_update_run(
        command=command,
        checked_count=result.checked,
        changed_count=result.sent + result.skipped,
        failed_count=result.failed,
        notes=f"sent={result.sent}, skipped={result.skipped}",
    )
    return result


def _docflow_headers(settings: Settings, api_key: str) -> dict[str, str]:
    """Build headers required by both Cloudflare Access and DocFlow itself."""
    headers = {"X-API-Key": api_key, "Accept": "application/json"}
    client_id = settings.cf_access_client_id
    client_secret = settings.cf_access_client_secret
    if bool(client_id) != bool(client_secret):
        raise ValueError(
            "CF_ACCESS_CLIENT_ID and CF_ACCESS_CLIENT_SECRET must be configured together"
        )
    if client_id:
        headers["CF-Access-Client-Id"] = client_id
        headers["CF-Access-Client-Secret"] = client_secret
    return headers


def _load_feedback_reviewers(
    base_url: str, *, headers: Mapping[str, str]
) -> tuple[str, str]:
    response = requests.get(
        f"{_api_root(base_url)}/settings/workflow",
        headers=dict(headers),
        timeout=30,
        allow_redirects=False,
    )
    if response.is_redirect:
        raise ValueError(
            "DocFlow request was redirected by Cloudflare Access. "
            "Configure CF_ACCESS_CLIENT_ID and CF_ACCESS_CLIENT_SECRET with a valid Service Token."
        )
    response.raise_for_status()
    content_type = response.headers.get("Content-Type", "").lower()
    if "application/json" not in content_type:
        raise ValueError(
            "DocFlow settings endpoint returned non-JSON content "
            f"({content_type or 'missing Content-Type'}); check Cloudflare Access."
        )
    try:
        reviewers = response.json().get("feedback_reviewers") or []
    except ValueError as exc:
        raise ValueError("DocFlow settings endpoint returned invalid JSON") from exc
    if len(reviewers) != 2 or not all(str(value).strip() for value in reviewers):
        raise ValueError("DocFlow workflow settings must contain exactly two feedback reviewers")
    return str(reviewers[0]), str(reviewers[1])


def _gds_as_step_2(reviewers: tuple[str, str]) -> tuple[str, str]:
    """Return reviewer order with GDS permanently mapped to Workflow Step 2."""
    cleaned = [reviewer.strip() for reviewer in reviewers]
    gds = [reviewer for reviewer in cleaned if reviewer.casefold() == "gds"]
    others = [reviewer for reviewer in cleaned if reviewer.casefold() != "gds"]
    if len(gds) != 1 or len(others) != 1:
        raise ValueError("DocFlow feedback reviewers must contain GDS exactly once for Step 2")
    return others[0], gds[0]


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


def _payload_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


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
