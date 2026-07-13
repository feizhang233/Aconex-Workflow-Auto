from __future__ import annotations

from collections.abc import Iterable, Mapping
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from .config import ROOT_DIR


DEFAULT_WORKFLOW_UPDATE_MANIFEST_PATH = (
    ROOT_DIR / "data" / "state" / "workflow_update_manifest.json"
)
SCHEMA_VERSION = 1
SYNC_TARGETS = ("google_sheet", "docflow")


def record_workflow_changes(
    changes: Iterable[Mapping[str, Any]],
    *,
    manifest_path: str | Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Merge workflow changes into the current ISO-week manifest."""
    path = _manifest_path(manifest_path)
    timestamp = _normalized_now(now)
    with _manifest_lock(path):
        manifest, dirty = _load_current_manifest(path, timestamp)
        for raw_change in changes:
            workflow_id = str(raw_change.get("workflow_id") or "").strip()
            workflow_number = str(raw_change.get("workflow_number") or "").strip()
            kind = str(raw_change.get("kind") or "").strip().casefold()
            if not workflow_id or not workflow_number:
                raise ValueError("workflow_id and workflow_number are required")
            if kind not in {"new", "status", "comments"}:
                raise ValueError(f"Unsupported workflow manifest change kind: {kind!r}")

            workflows = manifest["workflows"]
            entry = workflows.get(workflow_id)
            if entry is None:
                entry = _new_entry(workflow_id, workflow_number, timestamp)
                workflows[workflow_id] = entry
            entry["workflow_number"] = workflow_number
            entry["last_changed_at"] = _iso(timestamp)
            if kind not in entry["change_types"]:
                entry["change_types"].append(kind)

            event = {
                "kind": kind,
                "changed_at": str(raw_change.get("changed_at") or _iso(timestamp)),
            }
            for key in ("summary", "old", "new", "mail_ids"):
                if key in raw_change and raw_change.get(key) is not None:
                    event[key] = deepcopy(raw_change.get(key))
            if not _event_exists(entry["events"], event):
                entry["events"].append(event)

            _set_pending(entry["sync"]["google_sheet"])
            # Newly discovered Aconex workflows may not exist in DocFlow yet.
            # Only a later status change is eligible for an incremental PATCH;
            # DocFlow's existing 404 handling remains the final existence guard.
            if kind == "status":
                _set_pending(entry["sync"]["docflow"])
            dirty = True

        if dirty:
            manifest["updated_at"] = _iso(timestamp)
            _atomic_write(path, manifest)
        return deepcopy(manifest)


def pending_manifest_workflows(
    target: str,
    *,
    manifest_path: str | Path | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Return manifest entries that still require the requested downstream sync."""
    _validate_target(target)
    path = _manifest_path(manifest_path)
    timestamp = _normalized_now(now)
    with _manifest_lock(path):
        manifest, dirty = _load_current_manifest(path, timestamp)
        if dirty:
            _atomic_write(path, manifest)
        entries = [
            deepcopy(entry)
            for entry in manifest["workflows"].values()
            if entry["sync"][target]["status"] in {"pending", "failed"}
        ]
    return sorted(entries, key=_entry_sort_key)


def mark_manifest_sync(
    target: str,
    workflow_ids: Iterable[str],
    *,
    success: bool,
    error: str | None = None,
    manifest_path: str | Path | None = None,
    now: datetime | None = None,
) -> None:
    """Persist per-target sync success/failure for the supplied workflows."""
    _validate_target(target)
    ids = {str(value).strip() for value in workflow_ids if str(value).strip()}
    if not ids:
        return
    path = _manifest_path(manifest_path)
    timestamp = _normalized_now(now)
    with _manifest_lock(path):
        manifest, dirty = _load_current_manifest(path, timestamp)
        for workflow_id in ids:
            entry = manifest["workflows"].get(workflow_id)
            if entry is None:
                continue
            state = entry["sync"][target]
            state["status"] = "synced" if success else "failed"
            state["synced_at"] = _iso(timestamp) if success else None
            state["last_error"] = None if success else str(error or "Unknown sync failure")
            state["last_attempt_at"] = _iso(timestamp)
            dirty = True
        if dirty:
            manifest["updated_at"] = _iso(timestamp)
            _atomic_write(path, manifest)


def load_workflow_update_manifest(
    *,
    manifest_path: str | Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Load the manifest, applying week rollover rules when necessary."""
    path = _manifest_path(manifest_path)
    timestamp = _normalized_now(now)
    with _manifest_lock(path):
        manifest, dirty = _load_current_manifest(path, timestamp)
        if dirty:
            _atomic_write(path, manifest)
        return deepcopy(manifest)


def _load_current_manifest(path: Path, now: datetime) -> tuple[dict[str, Any], bool]:
    week = _week_key(now)
    if not path.exists():
        return _new_manifest(week, now), True
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot safely read workflow update manifest: {path}") from exc
    _validate_manifest(manifest)
    policy_changed = _apply_docflow_queue_policy(manifest)
    if manifest["week"] == week:
        return manifest, policy_changed

    previous_week = str(manifest["week"])
    carried = {
        workflow_id: entry
        for workflow_id, entry in manifest["workflows"].items()
        if _entry_requires_sync(entry)
    }
    for entry in carried.values():
        entry["carried_from_week"] = entry.get("carried_from_week") or previous_week
    rolled = _new_manifest(week, now)
    rolled["workflows"] = carried
    return rolled, True


def _new_manifest(week: str, now: datetime) -> dict[str, Any]:
    timestamp = _iso(now)
    return {
        "schema_version": SCHEMA_VERSION,
        "week": week,
        "created_at": timestamp,
        "updated_at": timestamp,
        "workflows": {},
    }


def _new_entry(workflow_id: str, workflow_number: str, now: datetime) -> dict[str, Any]:
    timestamp = _iso(now)
    return {
        "workflow_id": workflow_id,
        "workflow_number": workflow_number,
        "change_types": [],
        "first_changed_at": timestamp,
        "last_changed_at": timestamp,
        "events": [],
        "sync": {
            "google_sheet": _sync_state("pending"),
            "docflow": _sync_state("not_required"),
        },
    }


def _sync_state(status: str) -> dict[str, Any]:
    return {
        "status": status,
        "synced_at": None,
        "last_attempt_at": None,
        "last_error": None,
    }


def _set_pending(state: dict[str, Any]) -> None:
    state["status"] = "pending"
    state["synced_at"] = None
    state["last_error"] = None


def _entry_requires_sync(entry: Mapping[str, Any]) -> bool:
    sync = entry.get("sync") or {}
    return any(
        (sync.get(target) or {}).get("status") in {"pending", "failed"}
        for target in SYNC_TARGETS
    )


def _apply_docflow_queue_policy(manifest: dict[str, Any]) -> bool:
    """Remove legacy new-only entries from the incremental DocFlow queue."""
    changed = False
    for entry in manifest["workflows"].values():
        if "status" in (entry.get("change_types") or []):
            continue
        state = entry["sync"]["docflow"]
        if state.get("status") not in {"pending", "failed"}:
            continue
        state["status"] = "not_required"
        state["synced_at"] = None
        state["last_error"] = None
        changed = True
    return changed


def _event_exists(events: list[Mapping[str, Any]], candidate: Mapping[str, Any]) -> bool:
    encoded = json.dumps(candidate, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return any(
        json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")) == encoded
        for event in events
    )


def _validate_manifest(manifest: Any) -> None:
    if not isinstance(manifest, dict):
        raise RuntimeError("Workflow update manifest must contain a JSON object")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise RuntimeError(
            f"Unsupported workflow update manifest schema: {manifest.get('schema_version')!r}"
        )
    if not isinstance(manifest.get("week"), str) or not isinstance(manifest.get("workflows"), dict):
        raise RuntimeError("Workflow update manifest is missing week/workflows fields")
    for workflow_id, entry in manifest["workflows"].items():
        if not isinstance(entry, dict) or str(entry.get("workflow_id") or "") != str(workflow_id):
            raise RuntimeError(f"Invalid workflow update manifest entry: {workflow_id!r}")
        sync = entry.get("sync")
        if not isinstance(sync, dict) or any(target not in sync for target in SYNC_TARGETS):
            raise RuntimeError(f"Workflow update manifest entry has invalid sync state: {workflow_id!r}")


@contextmanager
def _manifest_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f"{path.name}.lock")
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _atomic_write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def _manifest_path(value: str | Path | None) -> Path:
    return Path(value) if value is not None else DEFAULT_WORKFLOW_UPDATE_MANIFEST_PATH


def _normalized_now(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        return current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def _week_key(value: datetime) -> str:
    year, week, _ = value.date().isocalendar()
    return f"{year:04d}-W{week:02d}"


def _iso(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat()


def _validate_target(target: str) -> None:
    if target not in SYNC_TARGETS:
        raise ValueError(f"Unknown workflow manifest sync target: {target!r}")


def _entry_sort_key(entry: Mapping[str, Any]) -> tuple[bool, int, str]:
    number = str(entry.get("workflow_number") or "")
    digits = "".join(character for character in number if character.isdigit())
    return (not bool(digits), int(digits or 0), number)
